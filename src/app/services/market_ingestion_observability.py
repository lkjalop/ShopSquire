"""Durable, tenant-scoped connector health and explicit dead-letter replay."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text

from src.app.services.market_signal import MarketSignal, ingest_with_receipt


_RUN_TABLE = "market_source_ingestion_run"
_WATERMARK_TABLE = "market_source_watermark"
_DEAD_TABLE = "market_source_dead_letter"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _has(db, name: str) -> bool:
    # Inspect through the session connection. Inspecting an Engine can check out
    # and roll back the same physical SQLite connection used by an in-flight
    # transaction (notably StaticPool tests), silently discarding a prior write.
    return inspect(db.connection()).has_table(name)


def load_watermark(db, *, tenant_id: str, source: str) -> str | None:
    if not _has(db, _WATERMARK_TABLE):
        return None
    row = db.execute(text(
        "SELECT watermark FROM market_source_watermark WHERE tenant_id=:tenant AND source=:source"
    ), {"tenant": tenant_id, "source": source}).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def persist_run(db, *, tenant_id: str, receipt: Any, started_at: str,
                finished_at: str, source_schema_version: int = 1) -> str | None:
    if not _has(db, _RUN_TABLE):
        return None
    run_id = str(uuid.uuid4())
    before = load_watermark(db, tenant_id=tenant_id, source=receipt.source)
    after = receipt.watermark_after or before
    db.execute(text("""
        INSERT INTO market_source_ingestion_run (
          id,tenant_id,source,source_schema_version,contract_schema_version,status,
          rows_read,accepted,outcomes_json,latency_ms,watermark_before,watermark_after,
          error_code,started_at,finished_at
        ) VALUES (
          :id,:tenant,:source,:source_schema,:contract,:status,:rows,:accepted,:outcomes,
          :latency,:before,:after,:error,:started,:finished
        )
    """), {
        "id": run_id, "tenant": tenant_id, "source": receipt.source,
        "source_schema": source_schema_version, "contract": receipt.schema_version,
        "status": receipt.status, "rows": receipt.rows_read, "accepted": receipt.accepted,
        "outcomes": json.dumps(receipt.outcomes, sort_keys=True),
        "latency": receipt.latency_ms, "before": before, "after": after,
        "error": receipt.error_code, "started": started_at, "finished": finished_at,
    })
    success = receipt.status == "completed"
    db.execute(text("""
        INSERT INTO market_source_watermark (
          tenant_id,source,source_schema_version,watermark,last_success_at,last_attempt_at,
          last_status,updated_at
        ) VALUES (:tenant,:source,:schema,:watermark,:success,:attempt,:status,:updated)
        ON CONFLICT(tenant_id,source) DO UPDATE SET
          source_schema_version=excluded.source_schema_version,
          watermark=CASE WHEN excluded.last_success_at IS NOT NULL THEN excluded.watermark
                         ELSE market_source_watermark.watermark END,
          last_success_at=COALESCE(excluded.last_success_at,market_source_watermark.last_success_at),
          last_attempt_at=excluded.last_attempt_at,last_status=excluded.last_status,
          updated_at=excluded.updated_at
    """), {
        "tenant": tenant_id, "source": receipt.source, "schema": source_schema_version,
        "watermark": after, "success": finished_at if success else None,
        "attempt": finished_at, "status": receipt.status, "updated": finished_at,
    })
    return run_id


def record_dead_letter(db, *, tenant_id: str, source: str, signal: Any,
                       reason_code: str, source_schema_version: int = 1) -> str | None:
    if not _has(db, _DEAD_TABLE) or signal is None:
        return None
    dead_id = str(uuid.uuid4())
    envelope = {
        "signal_type": signal.signal_type, "source": signal.source,
        "payload": signal.payload, "occurred_at": signal.occurred_at,
        "trust_score": signal.trust_score, "dedup_key": signal.dedup_key,
        "tenant_id": signal.tenant_id, "schema_version": signal.schema_version,
    }
    db.execute(text("""
        INSERT INTO market_source_dead_letter (
          id,tenant_id,source,dedup_key,source_schema_version,reason_code,envelope_json,
          status,attempts,first_failed_at
        ) VALUES (:id,:tenant,:source,:dedup,:schema,:reason,:envelope,'pending',0,:failed)
        ON CONFLICT(tenant_id,source,dedup_key,reason_code) DO NOTHING
    """), {
        "id": dead_id, "tenant": tenant_id, "source": source,
        "dedup": signal.dedup_key, "schema": source_schema_version,
        "reason": reason_code, "envelope": json.dumps(envelope, sort_keys=True, default=str),
        "failed": _now(),
    })
    return dead_id


def connector_health(db, *, tenant_id: str, window: int = 20) -> dict[str, Any]:
    if not _has(db, _RUN_TABLE):
        return {"schema_version": "market-connector-health-v1", "sources": [],
                "status": "not_configured", "authority": "operator_observability_only"}
    rows = db.execute(text("""
        SELECT source,status,rows_read,accepted,outcomes_json,latency_ms,error_code,finished_at
        FROM market_source_ingestion_run WHERE tenant_id=:tenant
        ORDER BY finished_at DESC
    """), {"tenant": tenant_id}).fetchall()
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row[0]), [])
        if len(grouped[str(row[0])]) < max(1, min(int(window), 100)):
            grouped[str(row[0])].append(row)
    watermarks: dict[str, dict[str, Any]] = {}
    if _has(db, _WATERMARK_TABLE):
        for row in db.execute(text("""
            SELECT source,source_schema_version,watermark,last_success_at,last_attempt_at,last_status
            FROM market_source_watermark WHERE tenant_id=:tenant
        """), {"tenant": tenant_id}).fetchall():
            watermarks[str(row[0])] = {
                "source_schema_version": row[1], "watermark": row[2],
                "last_success_at": row[3], "last_attempt_at": row[4], "last_status": row[5],
            }
    pending = 0
    if _has(db, _DEAD_TABLE):
        pending = int(db.execute(text(
            "SELECT COUNT(*) FROM market_source_dead_letter WHERE tenant_id=:tenant AND status='pending'"
        ), {"tenant": tenant_id}).scalar() or 0)
    sources = []
    for source, source_rows in sorted(grouped.items()):
        totals: dict[str, int] = {}
        for row in source_rows:
            for key, value in json.loads(row[4] or "{}").items():
                totals[key] = totals.get(key, 0) + int(value or 0)
        attempts = len(source_rows)
        read = sum(int(row[2] or 0) for row in source_rows)
        failures = sum(row[1] != "completed" for row in source_rows)
        sources.append({
            "source": source, "attempts": attempts,
            "status": "degraded" if failures else "healthy",
            "failure_rate": round(failures / attempts, 4),
            "zero_result_rate": round(sum(int(row[2] or 0) == 0 for row in source_rows) / attempts, 4),
            "accepted_rate": round(sum(int(row[3] or 0) for row in source_rows) / max(1, read), 4),
            "duplicate_rate": round(totals.get("duplicate", 0) / max(1, read), 4),
            "stale_rate": round(totals.get("stale", 0) / max(1, read), 4),
            "rejection_rate": round(sum(value for key, value in totals.items()
                                        if key not in {"accepted", "duplicate"}) / max(1, read), 4),
            "latency_ms_avg": round(sum(float(row[5] or 0) for row in source_rows) / attempts, 2),
            "last_error": next((row[6] for row in source_rows if row[6]), None),
            "last_observed_at": source_rows[0][7],
            **watermarks.get(source, {}),
        })
    return {"schema_version": "market-connector-health-v1", "sources": sources,
            "pending_dead_letters": pending, "status": "observed",
            "authority": "operator_observability_only"}


def list_dead_letters(db, *, tenant_id: str, status: str = "pending",
                      limit: int = 100) -> list[dict[str, Any]]:
    if not _has(db, _DEAD_TABLE):
        return []
    rows = db.execute(text("""
        SELECT id,source,dedup_key,source_schema_version,reason_code,status,attempts,
               first_failed_at,last_attempt_at,resolved_at,resolution
        FROM market_source_dead_letter
        WHERE tenant_id=:tenant AND status=:status
        ORDER BY first_failed_at LIMIT :limit
    """), {"tenant": tenant_id, "status": status, "limit": max(1, min(int(limit), 500))}).fetchall()
    return [{
        "id": row[0], "source": row[1], "dedup_key": row[2],
        "source_schema_version": row[3], "reason_code": row[4], "status": row[5],
        "attempts": row[6], "first_failed_at": row[7], "last_attempt_at": row[8],
        "resolved_at": row[9], "resolution": row[10],
    } for row in rows]


def replay_dead_letter(db, *, tenant_id: str, dead_letter_id: str) -> dict[str, Any]:
    """Explicit replay; policy-rejected evidence cannot be promoted by retry."""
    if not _has(db, _DEAD_TABLE):
        return {"status": "not_configured", "accepted": False}
    row = db.execute(text("""
        SELECT source_schema_version,reason_code,envelope_json,status
        FROM market_source_dead_letter WHERE id=:id AND tenant_id=:tenant
    """), {"id": dead_letter_id, "tenant": tenant_id}).fetchone()
    if not row:
        return {"status": "not_found", "accepted": False}
    if row[3] != "pending":
        return {"status": "already_resolved", "accepted": False}
    if int(row[0] or 0) != 1:
        return {"status": "incompatible_source_schema", "accepted": False}
    if row[1] not in {"storage_failed", "schema_unavailable"}:
        return {"status": "policy_rejection_requires_correction", "accepted": False,
                "reason_code": row[1]}
    payload = json.loads(row[2] or "{}")
    signal = MarketSignal(**payload)
    receipt = ingest_with_receipt(db, signal)
    attempted = _now()
    resolved = receipt.status in {"accepted", "duplicate"}
    db.execute(text("""
        UPDATE market_source_dead_letter SET attempts=attempts+1,last_attempt_at=:attempt,
          status=:status,resolved_at=:resolved,resolution=:resolution
        WHERE id=:id AND tenant_id=:tenant AND status='pending'
    """), {
        "attempt": attempted, "status": "resolved" if resolved else "pending",
        "resolved": attempted if resolved else None, "resolution": receipt.status,
        "id": dead_letter_id, "tenant": tenant_id,
    })
    return {"status": "resolved" if resolved else "retry_failed", "accepted": receipt.accepted,
            "ingestion_status": receipt.status, "authority": "operator_replay_only"}


__all__ = [
    "connector_health", "list_dead_letters", "load_watermark", "persist_run",
    "record_dead_letter", "replay_dead_letter",
]
