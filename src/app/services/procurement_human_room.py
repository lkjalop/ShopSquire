"""Tenant-scoped procurement human-room state machine with append-only events."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text


_ALLOWED = {
    "requested": {"assigned", "unavailable"},
    "assigned": {"operator_joined", "unavailable"},
    "operator_joined": {"responded", "unavailable"},
    "responded": set(),
    "unavailable": {"assigned"},
}


def _now(value: str | None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _event_id(tenant_id: str, key: str) -> str:
    return hashlib.sha256(f"{tenant_id}\x1f{key}".encode()).hexdigest()


def request_room(
    db,
    *,
    tenant_id: str,
    case_id: str,
    actor_id: str,
    idempotency_key: str,
    now_iso: str | None = None,
) -> dict[str, Any]:
    existing = db.execute(
        text(
            "SELECT id,state,assigned_operator_id,version FROM procurement_human_room "
            "WHERE tenant_id=:tenant AND case_id=:case_id"
        ),
        {"tenant": tenant_id, "case_id": case_id},
    ).first()
    if existing:
        return {
            "room_id": existing[0],
            "state": existing[1],
            "assigned_operator_id": existing[2],
            "version": int(existing[3]),
            "idempotent": True,
        }
    timestamp = _now(now_iso)
    room_id = f"phr-{uuid.uuid4().hex[:20]}"
    db.execute(
        text(
            "INSERT INTO procurement_human_room "
            "(id,tenant_id,case_id,state,assigned_operator_id,version,requested_at,updated_at) "
            "VALUES (:id,:tenant,:case_id,'requested',NULL,1,:timestamp,:timestamp)"
        ),
        {"id": room_id, "tenant": tenant_id, "case_id": case_id, "timestamp": timestamp},
    )
    db.execute(
        text(
            "INSERT INTO procurement_human_room_event "
            "(id,room_id,tenant_id,case_id,from_state,to_state,actor_type,actor_id,reason,idempotency_key,occurred_at) "
            "VALUES (:id,:room,:tenant,:case_id,NULL,'requested','buyer',:actor,NULL,:key,:timestamp)"
        ),
        {
            "id": _event_id(tenant_id, idempotency_key),
            "room": room_id,
            "tenant": tenant_id,
            "case_id": case_id,
            "actor": actor_id,
            "key": idempotency_key,
            "timestamp": timestamp,
        },
    )
    db.commit()
    return {
        "room_id": room_id,
        "state": "requested",
        "assigned_operator_id": None,
        "version": 1,
        "idempotent": False,
    }


def transition_room(
    db,
    *,
    tenant_id: str,
    case_id: str,
    to_state: str,
    actor_type: str,
    actor_id: str,
    idempotency_key: str,
    reason: str = "",
    now_iso: str | None = None,
) -> dict[str, Any]:
    prior_event = db.execute(
        text(
            "SELECT room_id,to_state FROM procurement_human_room_event "
            "WHERE tenant_id=:tenant AND idempotency_key=:key"
        ),
        {"tenant": tenant_id, "key": idempotency_key},
    ).first()
    if prior_event:
        return {"ok": True, "room_id": prior_event[0], "state": prior_event[1], "idempotent": True}
    room = db.execute(
        text(
            "SELECT id,state,version FROM procurement_human_room "
            "WHERE tenant_id=:tenant AND case_id=:case_id"
        ),
        {"tenant": tenant_id, "case_id": case_id},
    ).first()
    if not room:
        return {"ok": False, "state": None, "reason": "room_not_found"}
    current, target = str(room[1]), str(to_state)
    if target not in _ALLOWED.get(current, set()):
        return {
            "ok": False,
            "room_id": room[0],
            "state": current,
            "reason": f"illegal_transition:{current}->{target}",
        }
    timestamp = _now(now_iso)
    operator = actor_id if target in {"assigned", "operator_joined", "responded"} else None
    changed = db.execute(
        text(
            "UPDATE procurement_human_room SET state=:target,"
            "assigned_operator_id=COALESCE(:operator,assigned_operator_id),version=version+1,updated_at=:timestamp "
            "WHERE id=:id AND version=:version"
        ),
        {
            "target": target,
            "operator": operator,
            "timestamp": timestamp,
            "id": room[0],
            "version": int(room[2]),
        },
    ).rowcount
    if changed != 1:
        db.rollback()
        return {
            "ok": False,
            "room_id": room[0],
            "state": current,
            "reason": "concurrent_transition",
        }
    db.execute(
        text(
            "INSERT INTO procurement_human_room_event "
            "(id,room_id,tenant_id,case_id,from_state,to_state,actor_type,actor_id,reason,idempotency_key,occurred_at) "
            "VALUES (:id,:room,:tenant,:case_id,:prior,:target,:actor_type,:actor_id,:reason,:key,:timestamp)"
        ),
        {
            "id": _event_id(tenant_id, idempotency_key),
            "room": room[0],
            "tenant": tenant_id,
            "case_id": case_id,
            "prior": current,
            "target": target,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "reason": reason,
            "key": idempotency_key,
            "timestamp": timestamp,
        },
    )
    db.commit()
    return {
        "ok": True,
        "room_id": room[0],
        "state": target,
        "version": int(room[2]) + 1,
        "idempotent": False,
    }
