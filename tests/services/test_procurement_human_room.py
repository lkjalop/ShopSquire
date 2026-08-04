from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.procurement_human_room import request_room, transition_room


def _db():
    db = Session(create_engine("sqlite+pysqlite:///:memory:", future=True))
    db.execute(text("""CREATE TABLE procurement_human_room (
        id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, state TEXT,
        assigned_operator_id TEXT, version INTEGER, requested_at TEXT, updated_at TEXT,
        UNIQUE(tenant_id,case_id))"""))
    db.execute(text("""CREATE TABLE procurement_human_room_event (
        id TEXT PRIMARY KEY, room_id TEXT, tenant_id TEXT, case_id TEXT, from_state TEXT,
        to_state TEXT, actor_type TEXT, actor_id TEXT, reason TEXT, idempotency_key TEXT,
        occurred_at TEXT, UNIQUE(tenant_id,idempotency_key))"""))
    db.commit()
    return db


def test_procurement_room_complete_lifecycle_is_append_only_and_idempotent():
    db = _db()
    first = request_room(
        db, tenant_id="tenant-a", case_id="case-1", actor_id="buyer-1",
        idempotency_key="request-1", now_iso="2026-08-08T01:00:00+00:00",
    )
    assert first["state"] == "requested"
    states = (("assigned", "dispatch"), ("operator_joined", "op-7"), ("responded", "op-7"))
    for index, (state, actor) in enumerate(states, 1):
        result = transition_room(
            db, tenant_id="tenant-a", case_id="case-1", to_state=state,
            actor_type="operator", actor_id=actor, idempotency_key=f"event-{index}",
            now_iso=f"2026-08-08T01:0{index}:00+00:00",
        )
        assert result["ok"] and result["state"] == state
    replay = transition_room(
        db, tenant_id="tenant-a", case_id="case-1", to_state="responded",
        actor_type="operator", actor_id="op-7", idempotency_key="event-3",
    )
    assert replay["idempotent"] is True
    assert db.execute(text("SELECT COUNT(*) FROM procurement_human_room_event")).scalar_one() == 4


def test_procurement_room_rejects_join_before_assignment_and_supports_unavailable():
    db = _db()
    request_room(db, tenant_id="tenant-a", case_id="case-2", actor_id="buyer",
                 idempotency_key="request-2")
    illegal = transition_room(
        db, tenant_id="tenant-a", case_id="case-2", to_state="operator_joined",
        actor_type="operator", actor_id="op", idempotency_key="illegal",
    )
    assert illegal["ok"] is False and illegal["reason"].startswith("illegal_transition")
    unavailable = transition_room(
        db, tenant_id="tenant-a", case_id="case-2", to_state="unavailable",
        actor_type="system", actor_id="staffing", idempotency_key="unavailable",
    )
    assert unavailable["ok"] and unavailable["state"] == "unavailable"
