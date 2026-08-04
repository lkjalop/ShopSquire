"""Canonical internal escalation lifecycle; external ticket systems are adapters."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text


_STATES = {
    "requested": {"assigned", "unavailable"},
    "assigned": {"operator_joined", "unavailable"},
    "operator_joined": {"responded", "unavailable"},
    "responded": {"resolved", "unavailable"},
    "unavailable": {"assigned"},
    "resolved": set(),
}
_PRIORITIES = {"low", "medium", "high", "critical"}
_REASONS = {
    "clarification_required",
    "policy_prevented",
    "supplier_unavailable",
    "deadline_infeasible",
    "payment_expired",
    "security_quarantine",
    "system_degraded",
}


def _now(value: str | None = None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event_id(tenant_id: str, idempotency_key: str) -> str:
    return hashlib.sha256(f"{tenant_id}\x1f{idempotency_key}".encode()).hexdigest()


def request_escalation(
    db,
    *,
    tenant_id: str,
    domain: str,
    case_id: str,
    party_ref: str | None,
    priority: str,
    reason_code: str,
    triggering_observation_ref: str | None,
    trace_id: str | None,
    evidence_refs: list[str],
    policy_version: str,
    required_response_at: str | None,
    dedupe_key: str,
    actor_id: str,
    idempotency_key: str,
    order_line_id: str | None = None,
    ticket_id: str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    required = (tenant_id, domain, case_id, priority, reason_code, policy_version, dedupe_key)
    if not all(str(value or "").strip() for value in required):
        raise ValueError("escalation_scope_required")
    if priority not in _PRIORITIES:
        raise ValueError("unsupported_escalation_priority")
    if reason_code not in _REASONS:
        raise ValueError("unsupported_escalation_reason")
    existing = db.execute(
        text(
            "SELECT id,state,version FROM case_escalation "
            "WHERE tenant_id=:tenant AND dedupe_key=:dedupe"
        ),
        {"tenant": tenant_id, "dedupe": dedupe_key},
    ).first()
    if existing:
        return {
            "escalation_id": existing[0], "state": existing[1],
            "version": int(existing[2]), "idempotent": True,
        }
    timestamp = _now(now_iso)
    escalation_id = f"esc-{uuid.uuid4().hex}"
    evidence = sorted({str(ref).strip() for ref in evidence_refs if str(ref).strip()})
    db.execute(
        text(
            "INSERT INTO case_escalation "
            "(id,tenant_id,domain,party_ref,case_id,order_line_id,state,priority,reason_code,"
            "trigger_observation_ref,trace_id,evidence_refs_json,policy_version,required_response_at,"
            "assigned_operator_id,ticket_id,final_disposition,resulting_amendment_id,dedupe_key,version,"
            "created_at,updated_at) VALUES "
            "(:id,:tenant,:domain,:party,:case_id,:line,'requested',:priority,:reason,:observation,:trace,"
            ":evidence,:policy,:required,NULL,:ticket,NULL,NULL,:dedupe,1,:timestamp,:timestamp)"
        ),
        {
            "id": escalation_id, "tenant": tenant_id, "domain": domain,
            "party": party_ref, "case_id": case_id, "line": order_line_id,
            "priority": priority, "reason": reason_code,
            "observation": triggering_observation_ref, "trace": trace_id,
            "evidence": json.dumps(evidence, separators=(",", ":")),
            "policy": policy_version, "required": required_response_at,
            "ticket": ticket_id, "dedupe": dedupe_key, "timestamp": timestamp,
        },
    )
    db.execute(
        text(
            "INSERT INTO case_escalation_event "
            "(id,escalation_id,tenant_id,from_state,to_state,actor_type,actor_id,reason,"
            "idempotency_key,payload_json,occurred_at) VALUES "
            "(:id,:escalation,:tenant,NULL,'requested','requester',:actor,:reason,:key,:payload,:timestamp)"
        ),
        {
            "id": _event_id(tenant_id, idempotency_key), "escalation": escalation_id,
            "tenant": tenant_id, "actor": actor_id, "reason": reason_code,
            "key": idempotency_key,
            "payload": json.dumps({"priority": priority, "domain": domain}, separators=(",", ":")),
            "timestamp": timestamp,
        },
    )
    db.commit()
    return {"escalation_id": escalation_id, "state": "requested", "version": 1, "idempotent": False}


def transition_escalation(
    db,
    *,
    tenant_id: str,
    escalation_id: str,
    to_state: str,
    actor_type: str,
    actor_id: str,
    idempotency_key: str,
    reason: str = "",
    assigned_operator_id: str | None = None,
    final_disposition: str | None = None,
    resulting_amendment_id: str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    prior_event = db.execute(
        text(
            "SELECT to_state FROM case_escalation_event "
            "WHERE tenant_id=:tenant AND idempotency_key=:key"
        ),
        {"tenant": tenant_id, "key": idempotency_key},
    ).first()
    if prior_event:
        return {"ok": True, "state": prior_event[0], "idempotent": True}
    row = db.execute(
        text(
            "SELECT state,version,assigned_operator_id FROM case_escalation "
            "WHERE id=:id AND tenant_id=:tenant"
        ),
        {"id": escalation_id, "tenant": tenant_id},
    ).first()
    if not row:
        return {"ok": False, "state": None, "reason": "escalation_not_found"}
    current = str(row[0])
    if to_state not in _STATES.get(current, set()):
        return {"ok": False, "state": current, "reason": f"illegal_transition:{current}->{to_state}"}
    if to_state == "resolved" and not str(final_disposition or "").strip():
        return {"ok": False, "state": current, "reason": "final_disposition_required"}
    timestamp = _now(now_iso)
    operator = assigned_operator_id
    if to_state in {"assigned", "operator_joined", "responded", "resolved"}:
        operator = operator or actor_id or row[2]
    changed = db.execute(
        text(
            "UPDATE case_escalation SET state=:state,assigned_operator_id=COALESCE(:operator,assigned_operator_id),"
            "final_disposition=COALESCE(:disposition,final_disposition),"
            "resulting_amendment_id=COALESCE(:amendment,resulting_amendment_id),"
            "version=version+1,updated_at=:timestamp WHERE id=:id AND tenant_id=:tenant AND version=:version"
        ),
        {
            "state": to_state, "operator": operator, "disposition": final_disposition,
            "amendment": resulting_amendment_id, "timestamp": timestamp,
            "id": escalation_id, "tenant": tenant_id, "version": int(row[1]),
        },
    ).rowcount
    if changed != 1:
        db.rollback()
        return {"ok": False, "state": current, "reason": "concurrent_transition"}
    payload = {
        "assigned_operator_id": operator,
        "final_disposition": final_disposition,
        "resulting_amendment_id": resulting_amendment_id,
    }
    db.execute(
        text(
            "INSERT INTO case_escalation_event "
            "(id,escalation_id,tenant_id,from_state,to_state,actor_type,actor_id,reason,"
            "idempotency_key,payload_json,occurred_at) VALUES "
            "(:id,:escalation,:tenant,:prior,:target,:actor_type,:actor_id,:reason,:key,:payload,:timestamp)"
        ),
        {
            "id": _event_id(tenant_id, idempotency_key), "escalation": escalation_id,
            "tenant": tenant_id, "prior": current, "target": to_state,
            "actor_type": actor_type, "actor_id": actor_id, "reason": reason,
            "key": idempotency_key,
            "payload": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            "timestamp": timestamp,
        },
    )
    db.commit()
    return {"ok": True, "state": to_state, "version": int(row[1]) + 1, "idempotent": False}


def _view(row: Any, *, now_iso: str | None = None, include_party: bool = True) -> dict[str, Any]:
    now = _parse_time(_now(now_iso))
    created = _parse_time(str(row.created_at))
    required = _parse_time(str(row.required_response_at)) if row.required_response_at else None
    result = {
        "escalation_id": row.id,
        "domain": row.domain,
        "case_id": row.case_id,
        "order_line_id": row.order_line_id,
        "state": row.state,
        "priority": row.priority,
        "reason_code": row.reason_code,
        "trace_id": row.trace_id,
        "evidence_refs": json.loads(row.evidence_refs_json or "[]"),
        "policy_version": row.policy_version,
        "assigned_operator_id": row.assigned_operator_id,
        "ticket_id": row.ticket_id,
        "final_disposition": row.final_disposition,
        "resulting_amendment_id": row.resulting_amendment_id,
        "version": int(row.version),
        "queue_age_seconds": max(0, int((now - created).total_seconds())),
        "sla_status": "breached" if required and now > required else ("due" if required else "unbounded"),
    }
    if include_party:
        result["party_ref"] = row.party_ref
    return result


def get_escalation(db, *, tenant_id: str, escalation_id: str, now_iso: str | None = None) -> dict[str, Any]:
    row = db.execute(
        text("SELECT * FROM case_escalation WHERE tenant_id=:tenant AND id=:id"),
        {"tenant": tenant_id, "id": escalation_id},
    ).mappings().first()
    return _view(row, now_iso=now_iso) if row else {}


def list_open_escalations(db, *, tenant_id: str, now_iso: str | None = None) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            "SELECT * FROM case_escalation WHERE tenant_id=:tenant AND state!='resolved' "
            "ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 ELSE 3 END, created_at ASC"
        ),
        {"tenant": tenant_id},
    ).mappings().all()
    return [_view(row, now_iso=now_iso, include_party=False) for row in rows]

