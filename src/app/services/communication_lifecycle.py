"""Tenant-isolated, append-only communication state and grounding boundary."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import text

STATES = {
    "proposed", "approved", "queued", "delivered", "responded",
    "expired", "failed", "superseded", "quarantined",
}
_ALLOWED = {
    None: {"proposed", "responded", "quarantined"},
    "proposed": {"approved", "failed", "superseded", "quarantined"},
    "approved": {"queued", "failed", "superseded", "quarantined"},
    "queued": {"delivered", "failed", "superseded", "quarantined"},
    "delivered": {"responded", "expired", "superseded"},
    "responded": {"superseded"},
    "failed": {"queued", "superseded"},
    "quarantined": {"superseded"},
    "expired": {"superseded"},
    "superseded": set(),
}


def register_approved_grounding(
    db,
    *,
    tenant_id: str,
    grounding_type: str,
    source_ref: str,
    source_version: str,
    content: str,
    approved_by: str,
) -> str:
    tenant = str(tenant_id or "").strip()
    kind = str(grounding_type or "").strip().lower()
    if not tenant or kind not in {"fact", "template"}:
        raise ValueError("grounding_scope_required")
    if not all(str(value or "").strip() for value in (source_ref, source_version, approved_by)):
        raise ValueError("grounding_approval_required")
    digest = hashlib.sha256(str(content or "").encode("utf-8")).hexdigest()
    grounding_id = hashlib.sha256(
        f"{tenant}|{kind}|{source_ref}|{source_version}".encode("utf-8")
    ).hexdigest()
    existing = db.execute(text(
        "SELECT content_hash FROM communication_grounding "
        "WHERE tenant_id=:t AND id=:i"
    ), {"t": tenant, "i": grounding_id}).fetchone()
    if existing:
        if str(existing[0]) != digest:
            raise ValueError("grounding_version_content_mismatch")
        return grounding_id
    db.execute(text(
        "INSERT INTO communication_grounding "
        "(id,tenant_id,grounding_type,source_ref,source_version,content_hash,"
        "approval_status,approved_by,approved_at) "
        "VALUES (:i,:t,:k,:r,:v,:h,'approved',:a,:now)"
    ), {
        "i": grounding_id, "t": tenant, "k": kind, "r": str(source_ref),
        "v": str(source_version), "h": digest, "a": str(approved_by),
        "now": datetime.now(timezone.utc),
    })
    return grounding_id


def _latest_state(db, *, tenant_id: str, observation_id: str) -> Optional[str]:
    row = db.execute(text(
        "SELECT state FROM communication_lifecycle_event "
        "WHERE tenant_id=:t AND observation_id=:o "
        "ORDER BY sequence_no DESC LIMIT 1"
    ), {"t": tenant_id, "o": observation_id}).fetchone()
    return str(row[0]) if row else None


def _approved_refs(db, *, tenant_id: str, refs: Iterable[str]) -> set[str]:
    values = {str(ref) for ref in refs if str(ref or "").strip()}
    if not values:
        return set()
    rows = db.execute(text(
        "SELECT id FROM communication_grounding "
        "WHERE tenant_id=:t AND approval_status='approved'"
    ), {"t": tenant_id}).fetchall()
    return values.intersection({str(row[0]) for row in rows})


def _material_claim_refs(db, *, tenant_id: str, observation_id: str) -> set[str]:
    row = db.execute(text(
        "SELECT sanitized_payload_json FROM communication_observation "
        "WHERE tenant_id=:t AND id=:o"
    ), {"t": tenant_id, "o": observation_id}).fetchone()
    if not row:
        raise ValueError("communication_observation_not_found")
    try:
        payload = json.loads(row[0] or "{}")
    except (TypeError, ValueError):
        payload = {}
    return {
        str(claim.get("grounding_ref") or "")
        for claim in (payload.get("material_claims") or [])
        if isinstance(claim, dict)
    } - {""}


def append_transition(
    db,
    *,
    tenant_id: str,
    observation_id: str,
    state: str,
    idempotency_key: str,
    actor_type: str,
    actor_id: str = "",
    reason: str = "",
    grounding_refs: Optional[list[str]] = None,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    next_state = str(state or "").strip().lower()
    if not tenant or not observation_id or not idempotency_key or next_state not in STATES:
        raise ValueError("communication_transition_scope_required")
    duplicate = db.execute(text(
        "SELECT id,state FROM communication_lifecycle_event "
        "WHERE tenant_id=:t AND observation_id=:o AND idempotency_key=:k"
    ), {"t": tenant, "o": observation_id, "k": idempotency_key}).fetchone()
    if duplicate:
        return {"event_id": str(duplicate[0]), "state": str(duplicate[1]), "duplicate": True}
    current = _latest_state(db, tenant_id=tenant, observation_id=observation_id)
    if next_state not in _ALLOWED.get(current, set()):
        raise ValueError(f"illegal_communication_transition:{current}->{next_state}")

    refs = sorted({str(ref) for ref in (grounding_refs or []) if str(ref or "").strip()})
    if next_state in {"approved", "queued"}:
        required = _material_claim_refs(
            db, tenant_id=tenant, observation_id=observation_id
        )
        approved = _approved_refs(db, tenant_id=tenant, refs=refs)
        if required - approved:
            raise ValueError("ungrounded_material_claim")
    commercial_effect = "prevented" if next_state == "quarantined" else "none"
    sequence_no = int(db.execute(text(
        "SELECT COALESCE(MAX(sequence_no),0)+1 FROM communication_lifecycle_event "
        "WHERE tenant_id=:t AND observation_id=:o"
    ), {"t": tenant, "o": observation_id}).scalar() or 1)
    event_id = hashlib.sha256(
        f"{tenant}|{observation_id}|{idempotency_key}".encode("utf-8")
    ).hexdigest()
    db.execute(text(
        "INSERT INTO communication_lifecycle_event "
        "(id,tenant_id,observation_id,sequence_no,state,actor_type,actor_id,reason,"
        "grounding_refs_json,idempotency_key,commercial_effect,occurred_at) "
        "VALUES (:i,:t,:o,:seq,:s,:at,:ai,:r,:g,:k,:ce,:now)"
    ), {
        "i": event_id, "t": tenant, "o": observation_id, "seq": sequence_no, "s": next_state,
        "at": str(actor_type or "system"), "ai": str(actor_id or ""),
        "r": str(reason or ""), "g": json.dumps(refs),
        "k": str(idempotency_key), "ce": commercial_effect,
        "now": datetime.now(timezone.utc),
    })
    return {
        "event_id": event_id, "state": next_state, "previous_state": current,
        "duplicate": False, "commercial_effect": commercial_effect,
    }


def timeline(
    db, *, tenant_id: str, observation_id: Optional[str] = None,
    case_ref: Optional[str] = None, party_ref: Optional[str] = None,
    trace_ref: Optional[str] = None,
) -> list[dict[str, Any]]:
    if not any((observation_id, case_ref, party_ref, trace_ref)):
        raise ValueError("timeline_scope_required")
    if observation_id:
        where, reference = "e.observation_id=:ref", observation_id
    elif case_ref:
        where, reference = "o.case_ref=:ref", case_ref
    elif party_ref:
        where, reference = "o.party_ref=:ref", party_ref
    else:
        where, reference = "o.trace_ref=:ref", trace_ref
    rows = db.execute(text(
        "SELECT e.id,e.observation_id,e.state,e.actor_type,e.actor_id,e.reason,"
        "e.grounding_refs_json,e.commercial_effect,e.occurred_at "
        "FROM communication_lifecycle_event e "
        "JOIN communication_observation o ON o.id=e.observation_id AND o.tenant_id=e.tenant_id "
        f"WHERE e.tenant_id=:t AND {where} ORDER BY e.sequence_no"
    ), {"t": str(tenant_id), "ref": reference}).fetchall()
    return [{
        "event_id": row[0], "observation_id": row[1], "state": row[2],
        "actor_type": row[3], "actor_id": row[4], "reason": row[5],
        "grounding_refs": json.loads(row[6] or "[]"),
        "commercial_effect": row[7], "occurred_at": str(row[8]),
    } for row in rows]
