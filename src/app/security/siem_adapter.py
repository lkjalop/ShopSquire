from __future__ import annotations

from typing import Any, Dict, List, Optional
import json
import os
import time
import logging
import hashlib
from datetime import datetime, timedelta

import requests
from src.app.observability.metrics import record_security_handoff
from sqlalchemy import text
from src.app.models.db import db_session


logger = logging.getLogger("shopsquire.siem")


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _handoff_id(trace_id: str | None, decision_id: str | None, target: str) -> str:
    seed = f"{trace_id or decision_id or 'na'}:{target}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _ensure_handoff_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS security_handoff_attempts (
                      id TEXT PRIMARY KEY,
                      decision_id TEXT,
                      trace_id TEXT,
                      tenant_id TEXT,
                      target TEXT NOT NULL,
                      status TEXT NOT NULL,
                      attempts INTEGER DEFAULT 0,
                      max_attempts INTEGER DEFAULT 0,
                      first_attempt_at TEXT,
                      last_attempt_at TEXT,
                      next_attempt_at TEXT,
                      backoff_ms INTEGER DEFAULT 0,
                      last_error TEXT,
                      last_http_status INTEGER,
                      payload_json TEXT NOT NULL,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass


def _persist_handoff_attempt(
    *,
    handoff_id: str,
    decision_id: str | None,
    trace_id: str | None,
    tenant_id: str | None,
    target: str,
    status: str,
    attempts: int,
    max_attempts: int,
    next_attempt_at: str | None,
    backoff_ms: int,
    last_error: str | None,
    last_http_status: Optional[int],
    payload: Dict[str, Any],
) -> None:
    try:
        now = _utc_now_iso()
        _ensure_handoff_table()
        with db_session() as db:
            params = {
                "id": handoff_id,
                "decision_id": decision_id,
                "trace_id": trace_id,
                "tenant_id": tenant_id or "default",
                "target": target,
                "status": status,
                "attempts": int(attempts),
                "max_attempts": int(max_attempts),
                "first_attempt_at": now,
                "last_attempt_at": now,
                "next_attempt_at": next_attempt_at,
                "backoff_ms": int(max(0, backoff_ms)),
                "last_error": (last_error or "")[:1000] if last_error else None,
                "last_http_status": int(last_http_status) if last_http_status is not None else None,
                "payload_json": json.dumps(payload or {}, ensure_ascii=False),
                "created_at": now,
                "updated_at": now,
            }
            try:
                db.execute(
                    text(
                        """
                        INSERT INTO security_handoff_attempts (
                          id, decision_id, trace_id, tenant_id, target, status, attempts, max_attempts,
                          first_attempt_at, last_attempt_at, next_attempt_at, backoff_ms, last_error,
                          last_http_status, payload_json, created_at, updated_at
                        ) VALUES (
                          :id, :decision_id, :trace_id, :tenant_id, :target, :status, :attempts, :max_attempts,
                          :first_attempt_at, :last_attempt_at, :next_attempt_at, :backoff_ms, :last_error,
                          :last_http_status, :payload_json, :created_at, :updated_at
                        )
                        """
                    ),
                    params,
                )
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass
                db.execute(
                    text(
                        """
                        UPDATE security_handoff_attempts
                        SET decision_id=:decision_id,
                            trace_id=:trace_id,
                            tenant_id=:tenant_id,
                            target=:target,
                            status=:status,
                            attempts=:attempts,
                            max_attempts=:max_attempts,
                            last_attempt_at=:last_attempt_at,
                            next_attempt_at=:next_attempt_at,
                            backoff_ms=:backoff_ms,
                            last_error=:last_error,
                            last_http_status=:last_http_status,
                            payload_json=:payload_json,
                            updated_at=:updated_at
                        WHERE id=:id
                        """
                    ),
                    params,
                )
            db.commit()
    except Exception:
        pass


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_s: float = 4.0) -> tuple[bool, int | None, str | None]:
    try:
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout_s)
        code = int(r.status_code)
        return (200 <= code < 300), code, None if (200 <= code < 300) else f"http_{code}"
    except Exception as exc:
        return False, None, str(exc)


def build_normalized_security_event(
    *,
    source: str,
    tenant_id: str | None,
    decision_id: str | None,
    trace_id: str | None,
    message_id_hash: str | None,
    severity: str,
    verdict_action: str,
    route: str,
    escalation: str,
    reasons: List[str],
    tags: List[str],
    ioc_counts: Dict[str, Any] | None,
    risk_band: str | None,
    playbook_id: str | None,
    ticket_id: str | None,
    evidence: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "schema_version": "shopsquire.security.v1",
        "event_time": int(time.time()),
        "source": source,
        "tenant_id": tenant_id or "default",
        "decision_id": decision_id,
        "trace_id": trace_id or decision_id,
        "entity": {"message_id_hash": message_id_hash},
        "verdict": {
            "severity": severity,
            "action": verdict_action,
            "route": route,
            "escalation": escalation,
            "risk_band": risk_band,
        },
        "reasons": reasons or [],
        "tags": tags or [],
        "ioc": ioc_counts or {},
        "playbook_id": playbook_id,
        "ticket_id": ticket_id,
        "evidence": evidence or {},
    }


def map_security_event_for_splunk(event: Dict[str, Any]) -> Dict[str, Any]:
    verdict = event.get("verdict") if isinstance(event.get("verdict"), dict) else {}
    return {
        "time": int(time.time()),
        "sourcetype": "shopsquire:security_handoff",
        "source": "email_evaluate",
        "event": {
            "schema_version": str(event.get("schema_version") or "shopsquire.security.v1"),
            "event_time": int(event.get("event_time") or 0),
            "tenant_id": str(event.get("tenant_id") or "default"),
            "decision_id": event.get("decision_id"),
            "trace_id": event.get("trace_id"),
            "message_id_hash": ((event.get("entity") or {}).get("message_id_hash") if isinstance(event.get("entity"), dict) else None),
            "severity": str(verdict.get("severity") or "info"),
            "verdict_action": str(verdict.get("action") or "allow"),
            "route": str(verdict.get("route") or "auto_resolve"),
            "escalation": str(verdict.get("escalation") or "none"),
            "risk_band": verdict.get("risk_band"),
            "reasons": list(event.get("reasons") or []),
            "tags": list(event.get("tags") or []),
            "ioc": dict(event.get("ioc") or {}),
            "playbook_id": event.get("playbook_id"),
            "ticket_id": event.get("ticket_id"),
            "evidence": dict(event.get("evidence") or {}),
            "contract_version": "splunk.v1",
        },
    }


def map_security_event_for_sentinel(event: Dict[str, Any]) -> Dict[str, Any]:
    verdict = event.get("verdict") if isinstance(event.get("verdict"), dict) else {}
    entity = event.get("entity") if isinstance(event.get("entity"), dict) else {}
    return {
        "TimeGenerated": _utc_now_iso(),
        "TenantId_s": str(event.get("tenant_id") or "default"),
        "EventVendor_s": "ShopSquire",
        "EventProduct_s": "EmailSecurity",
        "EventSchemaVersion_s": str(event.get("schema_version") or "shopsquire.security.v1"),
        "EventTime_t": int(event.get("event_time") or 0),
        "DecisionId_s": str(event.get("decision_id") or ""),
        "TraceId_s": str(event.get("trace_id") or ""),
        "MessageIdHash_s": str(entity.get("message_id_hash") or ""),
        "Severity_s": str(verdict.get("severity") or "info"),
        "VerdictAction_s": str(verdict.get("action") or "allow"),
        "Route_s": str(verdict.get("route") or "auto_resolve"),
        "Escalation_s": str(verdict.get("escalation") or "none"),
        "RiskBand_s": str(verdict.get("risk_band") or ""),
        "Reasons_s": json.dumps(list(event.get("reasons") or []), ensure_ascii=False),
        "Tags_s": json.dumps(list(event.get("tags") or []), ensure_ascii=False),
        "Ioc_s": json.dumps(dict(event.get("ioc") or {}), ensure_ascii=False),
        "PlaybookId_s": str(event.get("playbook_id") or ""),
        "TicketId_s": str(event.get("ticket_id") or ""),
        "Evidence_s": json.dumps(dict(event.get("evidence") or {}), ensure_ascii=False),
        "ContractVersion_s": "sentinel.v1",
    }


def emit_security_handoff(event: Dict[str, Any]) -> Dict[str, Any]:
    """Emit normalized security event to SIEM/security middleware connectors.

    This is intentionally scoped to interoperability handoff only; it does not
    implement XDR-style endpoint/network telemetry.
    """
    status: Dict[str, Any] = {"sent": [], "failed": [], "retrying": [], "dlq": [], "details": []}
    max_attempts = max(1, int(os.getenv("SECURITY_HANDOFF_MAX_ATTEMPTS", "3") or 3))
    backoff_base = max(0.01, float(os.getenv("SECURITY_HANDOFF_BACKOFF_BASE_SECONDS", "0.2") or 0.2))
    backoff_max = max(backoff_base, float(os.getenv("SECURITY_HANDOFF_BACKOFF_MAX_SECONDS", "3.0") or 3.0))
    timeout_s = max(1.0, float(os.getenv("SECURITY_HANDOFF_TIMEOUT_SECONDS", "4.0") or 4.0))

    def _dispatch_target(
        target: str,
        url: str | None,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        *,
        persist_payload: Dict[str, Any],
    ) -> None:
        if not url:
            return
        hid = _handoff_id(str(event.get("trace_id") or ""), str(event.get("decision_id") or ""), target)
        last_error = None
        last_code: int | None = None
        for attempt in range(1, max_attempts + 1):
            ok, code, err = _post_json(url, headers, payload, timeout_s=timeout_s)
            last_error, last_code = err, code
            if ok:
                status["sent"].append(target)
                status["details"].append({"target": target, "status": "sent", "attempts": attempt, "http_status": code})
                try:
                    record_security_handoff(target, "sent")
                except Exception:
                    pass
                _persist_handoff_attempt(
                    handoff_id=hid,
                    decision_id=event.get("decision_id"),
                    trace_id=event.get("trace_id"),
                    tenant_id=event.get("tenant_id"),
                    target=target,
                    status="sent",
                    attempts=attempt,
                    max_attempts=max_attempts,
                    next_attempt_at=None,
                    backoff_ms=0,
                    last_error=None,
                    last_http_status=code,
                    payload=persist_payload,
                )
                return
            if attempt < max_attempts:
                backoff_s = min(backoff_max, backoff_base * (2 ** (attempt - 1)))
                next_attempt_at = (datetime.utcnow() + timedelta(seconds=backoff_s)).isoformat()
                status["retrying"].append(target)
                status["details"].append(
                    {
                        "target": target,
                        "status": "retrying",
                        "attempts": attempt,
                        "backoff_ms": int(backoff_s * 1000),
                        "http_status": code,
                        "error": err,
                    }
                )
                try:
                    record_security_handoff(target, "retrying")
                except Exception:
                    pass
                _persist_handoff_attempt(
                    handoff_id=hid,
                    decision_id=event.get("decision_id"),
                    trace_id=event.get("trace_id"),
                    tenant_id=event.get("tenant_id"),
                    target=target,
                    status="retrying",
                    attempts=attempt,
                    max_attempts=max_attempts,
                    next_attempt_at=next_attempt_at,
                    backoff_ms=int(backoff_s * 1000),
                    last_error=err,
                    last_http_status=code,
                    payload=persist_payload,
                )
                time.sleep(backoff_s)
                continue

            status["failed"].append(target)
            status["dlq"].append(target)
            status["details"].append(
                {
                    "target": target,
                    "status": "dlq",
                    "attempts": attempt,
                    "http_status": code,
                    "error": err,
                }
            )
            try:
                record_security_handoff(target, "failed")
                record_security_handoff(target, "dlq")
            except Exception:
                pass
            _persist_handoff_attempt(
                handoff_id=hid,
                decision_id=event.get("decision_id"),
                trace_id=event.get("trace_id"),
                tenant_id=event.get("tenant_id"),
                target=target,
                status="dlq",
                attempts=attempt,
                max_attempts=max_attempts,
                next_attempt_at=None,
                backoff_ms=0,
                last_error=err,
                last_http_status=code,
                payload=persist_payload,
            )

    configured_targets = 0

    # Generic SIEM webhook (simple interoperability target).
    siem_webhook_url = os.getenv("SIEM_WEBHOOK_URL")
    if siem_webhook_url:
        configured_targets += 1
        _dispatch_target(
            "siem_webhook",
            siem_webhook_url,
            {"Content-Type": "application/json"},
            event,
            persist_payload=event,
        )

    # Splunk HEC
    splunk_url = os.getenv("SPLUNK_HEC_URL")
    splunk_token = os.getenv("SPLUNK_HEC_TOKEN")
    if splunk_url and splunk_token:
        configured_targets += 1
        body = map_security_event_for_splunk(event)
        _dispatch_target(
            "splunk_hec",
            splunk_url,
            {"Authorization": f"Splunk {splunk_token}", "Content-Type": "application/json"},
            body,
            persist_payload=event,
        )

    # Elastic
    elastic_url = os.getenv("ELASTIC_SECURITY_EVENTS_URL")
    elastic_api_key = os.getenv("ELASTIC_API_KEY")
    if elastic_url:
        configured_targets += 1
        headers = {"Content-Type": "application/json"}
        if elastic_api_key:
            headers["Authorization"] = f"ApiKey {elastic_api_key}"
        _dispatch_target("elastic", elastic_url, headers, event, persist_payload=event)

    # Microsoft Sentinel via custom webhook/logic app
    sentinel_url = os.getenv("SENTINEL_INGEST_URL")
    if sentinel_url:
        configured_targets += 1
        sentinel_payload = map_security_event_for_sentinel(event)
        _dispatch_target("sentinel", sentinel_url, {"Content-Type": "application/json"}, sentinel_payload, persist_payload=event)

    # CrowdStrike/CSPM handoff webhooks (optional)
    cs_url = os.getenv("CROWDSTRIKE_INGEST_URL")
    if cs_url:
        configured_targets += 1
        _dispatch_target("crowdstrike", cs_url, {"Content-Type": "application/json"}, event, persist_payload=event)

    cspm_url = os.getenv("CSPM_INGEST_URL")
    if cspm_url:
        configured_targets += 1
        _dispatch_target("cspm", cspm_url, {"Content-Type": "application/json"}, event, persist_payload=event)

    # CyberStash MDR — CYBERSTASH_INGEST_URL + optional CYBERSTASH_API_KEY
    cyberstash_url = os.getenv("CYBERSTASH_INGEST_URL")
    cyberstash_key = os.getenv("CYBERSTASH_API_KEY")
    if cyberstash_url:
        configured_targets += 1
        cs_headers: Dict[str, str] = {"Content-Type": "application/json"}
        if cyberstash_key:
            cs_headers["x-api-key"] = cyberstash_key
        _dispatch_target("cyberstash", cyberstash_url, cs_headers, event, persist_payload=event)

    # Generic EDR JSON-webhook — GENERIC_EDR_INGEST_URL + optional GENERIC_EDR_API_KEY
    # Supports any vendor that accepts POST JSON (SentinelOne, Carbon Black, Cybereason, etc.)
    generic_edr_url = os.getenv("GENERIC_EDR_INGEST_URL")
    generic_edr_key = os.getenv("GENERIC_EDR_API_KEY")
    generic_edr_vendor = os.getenv("GENERIC_EDR_VENDOR", "generic_edr")
    if generic_edr_url:
        configured_targets += 1
        edr_headers: Dict[str, str] = {"Content-Type": "application/json"}
        if generic_edr_key:
            edr_headers["Authorization"] = f"Bearer {generic_edr_key}"
        _dispatch_target(generic_edr_vendor, generic_edr_url, edr_headers, event, persist_payload=event)

    if configured_targets == 0:
        hid = _handoff_id(str(event.get("trace_id") or ""), str(event.get("decision_id") or ""), "no_receiver")
        status["details"].append(
            {
                "target": "no_receiver",
                "status": "skipped",
                "reason": "no_security_receiver_configured",
            }
        )
        _persist_handoff_attempt(
            handoff_id=hid,
            decision_id=event.get("decision_id"),
            trace_id=event.get("trace_id"),
            tenant_id=event.get("tenant_id"),
            target="no_receiver",
            status="skipped",
            attempts=1,
            max_attempts=max_attempts,
            next_attempt_at=None,
            backoff_ms=0,
            last_error="no_security_receiver_configured",
            last_http_status=None,
            payload=event,
        )

    try:
        logger.info("security_handoff status=%s", json.dumps(status))
    except Exception:
        pass
    return status


def get_handoff_reliability(hours: int = 24) -> Dict[str, Any]:
    hours = max(1, min(int(hours or 24), 720))
    _ensure_handoff_table()
    out: Dict[str, Any] = {"window_hours": hours, "totals": {"attempts": 0, "sent": 0, "dlq": 0, "retrying": 0, "skipped": 0}, "by_target": []}
    try:
        since_iso = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT target,
                           COUNT(*) as total_rows,
                           SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) as sent_rows,
                           SUM(CASE WHEN status='dlq' THEN 1 ELSE 0 END) as dlq_rows,
                           SUM(CASE WHEN status='retrying' THEN 1 ELSE 0 END) as retrying_rows,
                           SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) as skipped_rows,
                           AVG(COALESCE(attempts,0)) as avg_attempts,
                           MAX(COALESCE(backoff_ms,0)) as max_backoff_ms
                    FROM security_handoff_attempts
                    WHERE updated_at >= :since_iso
                    GROUP BY target
                    ORDER BY target
                    """
                ),
                {"since_iso": since_iso},
            ).fetchall()
        by_target = []
        for r in rows or []:
            row = {
                "target": r[0],
                "attempts": int(r[1] or 0),
                "sent": int(r[2] or 0),
                "dlq": int(r[3] or 0),
                "retrying": int(r[4] or 0),
                "skipped": int(r[5] or 0),
                "avg_attempts": float(r[6] or 0.0),
                "max_backoff_ms": int(r[7] or 0),
            }
            by_target.append(row)
            out["totals"]["attempts"] += row["attempts"]
            out["totals"]["sent"] += row["sent"]
            out["totals"]["dlq"] += row["dlq"]
            out["totals"]["retrying"] += row["retrying"]
            out["totals"]["skipped"] += row["skipped"]
        out["by_target"] = by_target
    except Exception:
        pass
    return out


def list_handoff_dlq(limit: int = 100, offset: int = 0, target: str | None = None) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 100), 500))
    offset = max(0, int(offset or 0))
    _ensure_handoff_table()
    rows = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, decision_id, trace_id, tenant_id, target, status, attempts, max_attempts,
                           last_attempt_at, last_error, last_http_status, payload_json, updated_at
                    FROM security_handoff_attempts
                    WHERE status='dlq'
                      AND (:target IS NULL OR target=:target)
                    ORDER BY updated_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"target": target, "limit": limit, "offset": offset},
            ).fetchall()
    except Exception:
        rows = []
    items: List[Dict[str, Any]] = []
    for r in rows or []:
        payload = {}
        try:
            payload = json.loads(r[11] or "{}")
        except Exception:
            payload = {}
        items.append(
            {
                "id": r[0],
                "decision_id": r[1],
                "trace_id": r[2],
                "tenant_id": r[3],
                "target": r[4],
                "status": r[5],
                "attempts": int(r[6] or 0),
                "max_attempts": int(r[7] or 0),
                "last_attempt_at": r[8],
                "last_error": r[9],
                "last_http_status": r[10],
                "payload": payload,
                "updated_at": r[12],
            }
        )
    return {"items": items, "limit": limit, "offset": offset}


def requeue_handoff(item_id: str) -> Dict[str, Any]:
    _ensure_handoff_table()
    row = None
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT id, target, payload_json
                    FROM security_handoff_attempts
                    WHERE id=:id
                    """
                ),
                {"id": item_id},
            ).fetchone()
    except Exception:
        row = None
    if not row:
        return {"ok": False, "detail": "not_found", "id": item_id}
    target = str(row[1] or "")
    try:
        payload = json.loads(row[2] or "{}")
    except Exception:
        payload = {}

    # Re-emit to all configured targets if target is unavailable/empty; otherwise force target.
    handoff_result = emit_security_handoff(payload if isinstance(payload, dict) else {})
    if target:
        # Best-effort: if this target still fails it remains in DLQ from emit path.
        pass
    return {"ok": True, "id": item_id, "result": handoff_result}


def replay_handoff_dlq(*, limit: int = 50, target: str | None = None, dry_run: bool = False) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 50), 500))
    listed = list_handoff_dlq(limit=limit, offset=0, target=target)
    items = list(listed.get("items") or [])
    preview_ids = [str((i or {}).get("id") or "") for i in items if str((i or {}).get("id") or "").strip()]
    if dry_run:
        return {
            "dry_run": True,
            "requested_limit": limit,
            "target": target,
            "picked": len(preview_ids),
            "item_ids": preview_ids,
            "replayed": 0,
            "failed": 0,
            "results": [],
        }

    results: List[Dict[str, Any]] = []
    replayed = 0
    failed = 0
    for item_id in preview_ids:
        out = requeue_handoff(item_id)
        ok = bool(out.get("ok"))
        if ok:
            replayed += 1
        else:
            failed += 1
        results.append({"id": item_id, "ok": ok, "result": out.get("result"), "detail": out.get("detail")})
    return {
        "dry_run": False,
        "requested_limit": limit,
        "target": target,
        "picked": len(preview_ids),
        "item_ids": preview_ids,
        "replayed": replayed,
        "failed": failed,
        "results": results,
    }


def get_handoff_dashboard(*, hours: int = 24, dlq_limit: int = 20, target: str | None = None) -> Dict[str, Any]:
    reliability = get_handoff_reliability(hours=hours)
    dlq = list_handoff_dlq(limit=dlq_limit, offset=0, target=target)
    items = list(dlq.get("items") or [])
    totals = reliability.get("totals") if isinstance(reliability.get("totals"), dict) else {}
    attempts = int(totals.get("attempts") or 0)
    sent = int(totals.get("sent") or 0)
    dlq_n = int(totals.get("dlq") or 0)
    retrying = int(totals.get("retrying") or 0)
    skipped = int(totals.get("skipped") or 0)
    success_rate = float(sent / attempts) if attempts > 0 else 0.0
    return {
        "window_hours": int(reliability.get("window_hours") or hours),
        "target_filter": target,
        "summary": {
            "attempts": attempts,
            "sent": sent,
            "dlq": dlq_n,
            "retrying": retrying,
            "skipped": skipped,
            "success_rate": round(success_rate, 4),
            "has_failures": bool(dlq_n > 0 or retrying > 0),
        },
        "reliability": reliability,
        "dlq": {
            "limit": int(dlq.get("limit") or dlq_limit),
            "offset": int(dlq.get("offset") or 0),
            "count": len(items),
            "items": items,
        },
    }
