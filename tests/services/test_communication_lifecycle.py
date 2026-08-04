from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.communication_lifecycle import (
    append_transition,
    register_approved_grounding,
    timeline,
)


def _upgrade(connection, filename: str) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        _upgrade(connection, "20260812_communication_observations.py")
        _upgrade(connection, "20260826_communication_lifecycle.py")
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _observation(db, *, tenant: str, oid: str, claims=None):
    import json
    db.execute(text(
        "INSERT INTO communication_observation "
        "(id,tenant_id,party_type,direction,channel,provider_message_id,purpose,"
        "consent_status,authority,security_status,sanitized_payload_json,observed_at) "
        "VALUES (:i,:t,'buyer','outbound','synthetic',:i,'proposal','granted',"
        "'observation_only','accepted',:p,CURRENT_TIMESTAMP)"
    ), {"i": oid, "t": tenant, "p": json.dumps({"material_claims": claims or []})})


def test_transition_order_and_idempotency_are_enforced(db):
    _observation(db, tenant="tenant-a", oid="m1")
    with pytest.raises(ValueError, match="illegal_communication_transition"):
        append_transition(
            db, tenant_id="tenant-a", observation_id="m1", state="delivered",
            idempotency_key="deliver-1", actor_type="worker",
        )
    proposed = append_transition(
        db, tenant_id="tenant-a", observation_id="m1", state="proposed",
        idempotency_key="propose-1", actor_type="agent",
    )
    replay = append_transition(
        db, tenant_id="tenant-a", observation_id="m1", state="proposed",
        idempotency_key="propose-1", actor_type="agent",
    )
    assert proposed["event_id"] == replay["event_id"] and replay["duplicate"] is True


def test_ungrounded_material_claim_cannot_be_approved_or_queued(db):
    _observation(
        db, tenant="tenant-a", oid="m2",
        claims=[{"text": "Delivery is guaranteed Friday", "grounding_ref": "not-approved"}],
    )
    append_transition(
        db, tenant_id="tenant-a", observation_id="m2", state="proposed",
        idempotency_key="propose", actor_type="agent",
    )
    with pytest.raises(ValueError, match="ungrounded_material_claim"):
        append_transition(
            db, tenant_id="tenant-a", observation_id="m2", state="approved",
            idempotency_key="approve", actor_type="operator",
            grounding_refs=["not-approved"],
        )


def test_approved_versioned_fact_can_progress_to_delivery(db):
    grounding = register_approved_grounding(
        db, tenant_id="tenant-a", grounding_type="fact", source_ref="quote:q1",
        source_version="v3", content="Delivery date 2026-08-10", approved_by="operator-1",
    )
    _observation(
        db, tenant="tenant-a", oid="m3",
        claims=[{"text": "Delivery date is 10 August", "grounding_ref": grounding}],
    )
    for state in ("proposed", "approved", "queued", "delivered"):
        append_transition(
            db, tenant_id="tenant-a", observation_id="m3", state=state,
            idempotency_key=state, actor_type="operator" if state == "approved" else "system",
            grounding_refs=[grounding],
        )
    assert [event["state"] for event in timeline(
        db, tenant_id="tenant-a", observation_id="m3"
    )] == ["proposed", "approved", "queued", "delivered"]


def test_quarantine_is_tenant_isolated_and_prevents_commercial_effect(db):
    _observation(db, tenant="tenant-a", oid="same")
    _observation(db, tenant="tenant-b", oid="same-b")
    event = append_transition(
        db, tenant_id="tenant-a", observation_id="same", state="quarantined",
        idempotency_key="security-gate", actor_type="security", reason="prompt_injection",
    )
    assert event["commercial_effect"] == "prevented"
    assert len(timeline(db, tenant_id="tenant-a", observation_id="same")) == 1
    assert timeline(db, tenant_id="tenant-b", observation_id="same") == []


def test_outbound_queue_projects_approved_queued_and_delivered(db):
    from src.app.services.fulfillment import outbound_queue
    db.execute(text(outbound_queue._DDL))
    queued = outbound_queue.enqueue(
        db, tenant_id="tenant-a", case_id="case-1", recipient="supplier@example.test",
        subject="RFQ case-1", body="Please quote 10 units", idempotency_key="content-1",
        actor_type="human", actor_id="operator-1", transition_event="supplier_rfq_sent",
        grounding_materials=[{
            "grounding_type": "fact",
            "source_ref": "INV-1",
            "source_version": "v1",
            "content": "Authoritative shortfall is 10 units",
        }],
    )
    class Sent:
        status = "sent"
        provider_ref = "provider-1"
        detail = ""

    class Transport:
        def send(self, **_kwargs):
            return Sent()

    outbound_queue.process_pending(
        db, tenant_id="tenant-a", transport=Transport(), only_key="content-1"
    )
    row = db.execute(text(
        "SELECT id FROM communication_observation "
        "WHERE tenant_id='tenant-a' AND provider_message_id=:m"
    ), {"m": queued["message_id"]}).fetchone()
    assert row
    events = timeline(
        db, tenant_id="tenant-a", observation_id=str(row[0])
    )
    assert [event["state"] for event in events] == [
        "proposed", "approved", "queued", "delivered",
    ]
    assert events[1]["grounding_refs"] and events[2]["grounding_refs"]
    payload = db.execute(text(
        "SELECT sanitized_payload_json FROM communication_observation "
        "WHERE tenant_id='tenant-a' AND id=:i"
    ), {"i": str(row[0])}).scalar()
    import json
    claims = json.loads(payload)["material_claims"]
    assert claims[0]["text"] == "Authoritative shortfall is 10 units"
    assert claims[0]["grounding_ref"] == events[1]["grounding_refs"][0]
