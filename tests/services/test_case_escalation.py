import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.case_escalation import (
    get_escalation,
    list_escalation_timeline,
    list_open_escalations,
    request_escalation,
    transition_escalation,
)


def _db() -> Session:
    db = Session(create_engine("sqlite+pysqlite:///:memory:", future=True))
    db.execute(text("""
        CREATE TABLE case_escalation (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, domain TEXT NOT NULL,
            party_ref TEXT, case_id TEXT NOT NULL, order_line_id TEXT,
            state TEXT NOT NULL, priority TEXT NOT NULL, reason_code TEXT NOT NULL,
            trigger_observation_ref TEXT, trace_id TEXT, evidence_refs_json TEXT NOT NULL,
            policy_version TEXT NOT NULL, required_response_at TEXT,
            assigned_operator_id TEXT, ticket_id TEXT, final_disposition TEXT,
            resulting_amendment_id TEXT, dedupe_key TEXT NOT NULL, version INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(tenant_id,dedupe_key)
        )
    """))
    db.execute(text("""
        CREATE TABLE case_escalation_event (
            id TEXT PRIMARY KEY, escalation_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
            from_state TEXT, to_state TEXT NOT NULL, actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL, reason TEXT, idempotency_key TEXT NOT NULL,
            payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL,
            UNIQUE(tenant_id,idempotency_key)
        )
    """))
    db.commit()
    return db


def _request(db: Session, *, tenant: str = "tenant-a", dedupe: str = "case-1:deadline"):
    return request_escalation(
        db,
        tenant_id=tenant,
        domain="procurement",
        case_id="case-1",
        party_ref="buyer-hash",
        priority="high",
        reason_code="deadline_infeasible",
        triggering_observation_ref="obs-1",
        trace_id="trace-1",
        evidence_refs=["promise/calc-1", "calendar/au-nsw-v4"],
        policy_version="escalation-v1",
        required_response_at="2026-08-04T05:00:00+00:00",
        dedupe_key=dedupe,
        actor_id="buyer-hash",
        idempotency_key="request-1",
        now_iso="2026-08-04T03:00:00+00:00",
    )


def test_request_is_tenant_scoped_deduplicated_and_preserves_evidence() -> None:
    db = _db()
    first = _request(db)
    replay = _request(db)
    other_tenant = _request(db, tenant="tenant-b")

    assert first["state"] == "requested" and first["idempotent"] is False
    assert replay["escalation_id"] == first["escalation_id"]
    assert replay["idempotent"] is True
    assert other_tenant["escalation_id"] != first["escalation_id"]
    stored = get_escalation(
        db,
        tenant_id="tenant-a",
        escalation_id=first["escalation_id"],
        now_iso="2026-08-04T03:00:00+00:00",
    )
    assert stored["evidence_refs"] == ["calendar/au-nsw-v4", "promise/calc-1"]
    assert stored["queue_age_seconds"] == 0


def test_lifecycle_supports_unavailable_reassignment_response_and_resolution() -> None:
    db = _db()
    escalation_id = _request(db)["escalation_id"]
    steps = [
        ("assigned", "dispatcher", "dispatch", {}),
        ("unavailable", "operator", "op-1", {"reason": "shift_ended"}),
        ("assigned", "dispatcher", "dispatch", {"assigned_operator_id": "op-2"}),
        ("operator_joined", "operator", "op-2", {}),
        ("responded", "operator", "op-2", {}),
        (
            "resolved",
            "operator",
            "op-2",
            {"final_disposition": "buyer_selected_split", "resulting_amendment_id": "amend-7"},
        ),
    ]
    for index, (state, actor_type, actor_id, payload) in enumerate(steps, 1):
        result = transition_escalation(
            db,
            tenant_id="tenant-a",
            escalation_id=escalation_id,
            to_state=state,
            actor_type=actor_type,
            actor_id=actor_id,
            idempotency_key=f"transition-{index}",
            now_iso=f"2026-08-04T03:{index:02d}:00+00:00",
            **payload,
        )
        assert result["ok"] is True and result["state"] == state

    final = get_escalation(db, tenant_id="tenant-a", escalation_id=escalation_id)
    assert final["final_disposition"] == "buyer_selected_split"
    assert final["resulting_amendment_id"] == "amend-7"
    assert db.execute(text("SELECT COUNT(*) FROM case_escalation_event")).scalar_one() == 7


def test_illegal_transition_and_resolution_without_disposition_fail_closed() -> None:
    db = _db()
    escalation_id = _request(db)["escalation_id"]
    illegal = transition_escalation(
        db,
        tenant_id="tenant-a",
        escalation_id=escalation_id,
        to_state="responded",
        actor_type="operator",
        actor_id="op-1",
        idempotency_key="illegal",
    )
    assert illegal["ok"] is False
    assert illegal["reason"] == "illegal_transition:requested->responded"

    for index, state in enumerate(("assigned", "operator_joined", "responded"), 1):
        transition_escalation(
            db, tenant_id="tenant-a", escalation_id=escalation_id,
            to_state=state, actor_type="operator", actor_id="op-1",
            idempotency_key=f"valid-{index}",
        )
    unresolved = transition_escalation(
        db,
        tenant_id="tenant-a",
        escalation_id=escalation_id,
        to_state="resolved",
        actor_type="operator",
        actor_id="op-1",
        idempotency_key="missing-disposition",
    )
    assert unresolved == {
        "ok": False,
        "state": "responded",
        "reason": "final_disposition_required",
    }


def test_internal_queue_reports_sla_state_without_external_credentials() -> None:
    db = _db()
    _request(db)
    rows = list_open_escalations(
        db,
        tenant_id="tenant-a",
        now_iso="2026-08-04T05:05:00+00:00",
    )
    assert len(rows) == 1
    assert rows[0]["sla_status"] == "breached"
    assert rows[0]["queue_age_seconds"] == 7500
    assert "party_ref" not in rows[0]
    assert json.dumps(rows[0])


def test_timeline_is_tenant_scoped_and_append_only() -> None:
    db = _db()
    escalation_id = _request(db)["escalation_id"]
    transition_escalation(
        db,
        tenant_id="tenant-a",
        escalation_id=escalation_id,
        to_state="assigned",
        actor_type="dispatcher",
        actor_id="queue",
        idempotency_key="assign-timeline",
        assigned_operator_id="op-1",
    )

    timeline = list_escalation_timeline(
        db, tenant_id="tenant-a", escalation_id=escalation_id
    )
    assert [event["to_state"] for event in timeline] == ["requested", "assigned"]
    assert timeline[1]["payload"]["assigned_operator_id"] == "op-1"
    assert list_escalation_timeline(
        db, tenant_id="tenant-b", escalation_id=escalation_id
    ) == []
