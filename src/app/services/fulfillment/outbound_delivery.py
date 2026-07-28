"""Tenant-scoped orchestration around durable outbound delivery."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import text

from src.app.services.fulfillment import outbound_queue


def replay_deferred_send_transitions(db, sent_rows: list) -> Dict[str, int]:
    """Replay only the exact workflow transition persisted with an approved send."""
    from src.app.services.fulfillment import workflow
    from src.app.services.fulfillment.domain import Actor, ActorType

    advanced, skipped = 0, 0
    for row in sent_rows or []:
        event = str(row.get("transition_event") or "")
        actor_type = str(row.get("actor_type") or "")
        case_id = str(row.get("case_id") or "")
        if not (event and actor_type and case_id):
            skipped += 1
            continue
        try:
            actor = Actor(ActorType(actor_type), str(row.get("actor_id") or ""))
            result = workflow.transition(
                db,
                case_id=case_id,
                event=event,
                actor=actor,
                reason_code="deferred_send_delivered",
                evidence={"provider_ref": row.get("provider_ref", ""), "deferred": True},
                state_patch={
                    "outbound": {
                        "provider_ref": row.get("provider_ref", ""),
                        "content_hash": row.get("content_hash"),
                        "status": "sent",
                        "transport": "queued",
                    }
                },
            )
            if getattr(result, "ok", False):
                advanced += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return {"advanced": advanced, "skipped": skipped}


def process_tenant(db, *, tenant_id: str, limit: int = 50) -> Dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_id_required")
    out = outbound_queue.process_pending(
        db,
        tenant_id=tenant,
        limit=max(1, min(int(limit), 100)),
    )
    if out.get("error"):
        raise RuntimeError(str(out["error"]))
    out["transitions"] = replay_deferred_send_transitions(
        db,
        out.get("sent_rows") or [],
    )
    return out


def create_job(
    db,
    *,
    job_id: str,
    tenant_id: str,
    requested_by: str,
    limit: int,
) -> None:
    db.execute(text("""
        INSERT INTO outbound_delivery_job (
            id, tenant_id, status, requested_by, limit_count, submitted_at
        ) VALUES (
            :id, :tenant, 'queued', :requested_by, :limit, :submitted_at
        )
    """), {
        "id": str(job_id),
        "tenant": str(tenant_id),
        "requested_by": str(requested_by),
        "limit": max(1, min(int(limit), 100)),
        "submitted_at": datetime.now(timezone.utc),
    })
    db.commit()


def mark_job_started(db, *, job_id: str, tenant_id: str) -> None:
    result = db.execute(text("""
        UPDATE outbound_delivery_job
        SET status='running', started_at=:started
        WHERE id=:id AND tenant_id=:tenant
          AND status IN ('queued','running','failed')
    """), {
        "id": str(job_id),
        "tenant": str(tenant_id),
        "started": datetime.now(timezone.utc),
    })
    if getattr(result, "rowcount", 0) != 1:
        db.rollback()
        raise RuntimeError("outbound_job_claim_failed")
    db.commit()


def finish_job(
    db,
    *,
    job_id: str,
    tenant_id: str,
    result: Dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    db.execute(text("""
        UPDATE outbound_delivery_job
        SET status=:status, result_json=:result, error=:error, completed_at=:completed
        WHERE id=:id AND tenant_id=:tenant
    """), {
        "status": "failed" if error else "completed",
        "result": json.dumps(result or {}, sort_keys=True, default=str),
        "error": str(error or "")[:1000] or None,
        "completed": datetime.now(timezone.utc),
        "id": str(job_id),
        "tenant": str(tenant_id),
    })
    db.commit()


def job_status(db, *, job_id: str, tenant_id: str) -> Dict[str, Any]:
    row = db.execute(text("""
        SELECT id, tenant_id, status, requested_by, limit_count, result_json,
               error, submitted_at, started_at, completed_at
        FROM outbound_delivery_job
        WHERE id=:id AND tenant_id=:tenant
    """), {"id": str(job_id), "tenant": str(tenant_id)}).fetchone()
    if not row:
        return {}
    try:
        result = json.loads(row[5] or "{}")
    except (TypeError, ValueError):
        result = {}
    return {
        "job_id": row[0],
        "tenant_id": row[1],
        "status": row[2],
        "requested_by": row[3],
        "limit": int(row[4]),
        "result": result,
        "error": row[6],
        "submitted_at": str(row[7]),
        "started_at": str(row[8]) if row[8] else None,
        "completed_at": str(row[9]) if row[9] else None,
    }
