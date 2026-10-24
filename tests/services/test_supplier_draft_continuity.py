"""One versioned composition is shown in chat, reviewed, then dispatched."""

import json

import pytest
from sqlalchemy import text

import tests.services.test_supplier_enquiry_journey as shared_fixtures
from tests.services.test_supplier_enquiry_journey import prepare, create, NOW, FakeTransport

from src.app.services import supplier_enquiry_journey as journey
from src.app.services.shortfall_enquiry_preview import shortfall_draft
from src.app.services.fulfillment import outbound_queue as queue

db = shared_fixtures.db


def state(db):
    value = dict(
        case_id="case",
        revision=2,
        requested_quantity=30,
        budget=dict(amount_minor=150000, currency="AUD", scope="per_unit"),
        destinations=[dict(location_ref="Sydney", quantity=30)],
        temporal=dict(original_expression="within two weeks", resolution_status="unresolved"),
    )
    db.execute(
        text(
            "INSERT INTO conversation_case_state "
            "(id,tenant_id,case_id,session_epoch,subject_ref,version,state_json,created_at,updated_at) "
            "VALUES ('state','shop','case','epoch','subject',2,:state,:now,:now)"
        ),
        dict(state=json.dumps({"procurement_case_state": value}), now=NOW.isoformat()),
    )
    db.commit()
    return value


def test_preview_reviewed_and_sent_message_share_the_same_artifact(db):
    prepare(db)
    canonical = state(db)
    preview = shortfall_draft(
        db, tenant_id="shop", case_id="case", revision=2, state=canonical, now=NOW
    )
    row = create(db)
    reviewed = journey.view(db, tenant_id="shop", enquiry_id=row["id"], now=NOW)
    assert reviewed["message"]["body"] == preview["body"]
    assert reviewed["draft_artifact"]["content_hash"] == preview["draft_artifact"]["content_hash"]
    assert "15 units" in reviewed["message"]["body"]
    assert "Sydney" in reviewed["message"]["body"] and "two weeks" in reviewed["message"]["body"]
    journey.approve(
        db, tenant_id="shop", enquiry_id=row["id"], approver_principal="bob-key", now=NOW
    )

    class RecordingTransport(FakeTransport):
        message = None

        def send(self, **message):
            self.message = message
            return super().send(**message)

    tx = RecordingTransport()
    journey.dispatch(db, tenant_id="shop", enquiry_id=row["id"], transport=tx, now=NOW)
    assert tx.message["body"] == reviewed["message"]["body"]
    assert tx.message["subject"] == reviewed["message"]["subject"]
    assert tx.message["to"] == reviewed["message"]["recipient"]
    assert tx.calls == 1


def test_budget_disclosure_edit_requires_fresh_review_and_survives_reload(db):
    prepare(db)
    state(db)
    row = create(db)
    journey.approve(
        db, tenant_id="shop", enquiry_id=row["id"], approver_principal="bob-key", now=NOW
    )
    old = journey.view(db, tenant_id="shop", enquiry_id=row["id"], now=NOW)
    assert "AUD 1500.00" in old["message"]["body"]
    changed = journey.revise_draft(
        db,
        tenant_id="shop",
        enquiry_id=row["id"],
        operator_principal="alice-key-1",
        expected_version=1,
        include_budget=False,
        now=NOW,
    )
    assert changed["draft_version"] == 2 and changed["status"] == "pending"
    assert changed["draft_artifact"]["content_hash"] != old["draft_artifact"]["content_hash"]
    assert "AUD 1500.00" not in changed["message"]["body"]
    assert "15 units" in changed["message"]["body"] and "Sydney" in changed["message"]["body"]
    tx = FakeTransport()
    with pytest.raises(ValueError, match="approved"):
        journey.dispatch(db, tenant_id="shop", enquiry_id=row["id"], transport=tx, now=NOW)
    assert tx.calls == 0
    assert (
        journey.view(db, tenant_id="shop", enquiry_id=row["id"], now=NOW)["message"]
        == changed["message"]
    )
    with pytest.raises(ValueError, match="draft_version_conflict"):
        journey.revise_draft(
            db,
            tenant_id="shop",
            enquiry_id=row["id"],
            operator_principal="alice-key-1",
            expected_version=1,
            include_budget=True,
            now=NOW,
        )
    journey.approve(
        db, tenant_id="shop", enquiry_id=row["id"], approver_principal="bob-key", now=NOW
    )
    journey.dispatch(db, tenant_id="shop", enquiry_id=row["id"], transport=tx, now=NOW)
    assert tx.calls == 1


def test_enqueued_draft_cannot_be_silently_edited(db):
    prepare(db)
    state(db)
    row = create(db)
    row = journey.approve(
        db, tenant_id="shop", enquiry_id=row["id"], approver_principal="bob-key", now=NOW
    )
    queue.enqueue(
        db,
        **journey._effect(row, "bob-key"),
        person_approval_id=row["approval_id"],
        now_iso=NOW.isoformat(),
    )
    with pytest.raises(ValueError, match="draft_already_queued"):
        journey.revise_draft(
            db,
            tenant_id="shop",
            enquiry_id=row["id"],
            operator_principal="alice-key-1",
            expected_version=1,
            include_budget=False,
            now=NOW,
        )


def test_foreign_operator_cannot_edit_owned_draft(db):
    prepare(db)
    state(db)
    row = create(db)
    with pytest.raises(ValueError, match="active_person_membership_required"):
        journey.revise_draft(
            db,
            tenant_id="shop",
            enquiry_id=row["id"],
            operator_principal="foreign",
            expected_version=1,
            include_budget=False,
            now=NOW,
        )


def test_editor_cannot_approve_their_own_revised_message(db):
    prepare(db)
    state(db)
    row = create(db)
    journey.revise_draft(
        db,
        tenant_id="shop",
        enquiry_id=row["id"],
        operator_principal="bob-key",
        expected_version=1,
        include_budget=False,
        now=NOW,
    )
    with pytest.raises(ValueError, match="distinct_people_required"):
        journey.approve(
            db, tenant_id="shop", enquiry_id=row["id"], approver_principal="bob-key", now=NOW
        )


def test_tampered_draft_cannot_reach_the_transport_even_after_enqueue(db):
    prepare(db)
    state(db)
    row = create(db)
    row = journey.approve(
        db, tenant_id="shop", enquiry_id=row["id"], approver_principal="bob-key", now=NOW
    )
    queue.enqueue(
        db,
        **journey._effect(row, "bob-key"),
        person_approval_id=row["approval_id"],
        now_iso=NOW.isoformat(),
    )
    db.execute(text("UPDATE supplier_enquiry_draft SET draft_json='{}'"))
    db.commit()
    tx = FakeTransport()
    queue.process_pending(db, tenant_id="shop", transport=tx, now_iso=NOW.isoformat())
    assert tx.calls == 0
    assert (
        queue.get_by_key(db, tenant_id="shop", idempotency_key="supplier-enquiry:" + row["id"])[
            "status"
        ]
        == "blocked_authority"
    )
