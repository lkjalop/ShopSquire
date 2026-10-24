"""Chat must display the saved reviewed version after operator edits, never regenerate it."""

from datetime import datetime, timedelta, timezone
import json

import pytest
from sqlalchemy import text

from src.app.deps import hash_uid
from src.app.services.case_task_delivery import deliver_case_task
from src.app.services import supplier_enquiry_journey as journey
import tests.services.test_supplier_draft_continuity as continuity
import tests.services.test_supplier_enquiry_journey as fixtures

db = fixtures.db


def prepare(db):
    fixtures.prepare(db)
    continuity.state(db)
    db.execute(text("ALTER TABLE shopping_cases ADD COLUMN uid TEXT"))
    db.execute(text("UPDATE shopping_cases SET uid='owned-buyer'"))
    db.execute(
        text("UPDATE conversation_case_state SET subject_ref=:subject"),
        {"subject": hash_uid("owned-buyer")},
    )
    db.execute(
        text("UPDATE inventory_reservation SET expires_at=:expiry"),
        {"expiry": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()},
    )
    db.commit()
    row = fixtures.create(db)
    db.commit()  # The operator API commits before a separate chat request reads.
    return row


def read(db, *, tenant="shop", buyer="owned-buyer"):
    out = {
        "case_id": "case",
        "operation_id": "owned-preview-operation",
        "read_only_case_task": True,
    }
    deliver_case_task(
        out=out,
        request_db=db,
        tenant_id=tenant,
        uid=buyer,
        session_epoch="epoch",
        query="Show the supplier email draft for my current request.",
    )
    return out["email_draft"]


def test_chat_retains_the_operator_edited_budget_choice_and_exact_version(db):
    row = prepare(db)
    changed = journey.revise_draft(
        db,
        tenant_id="shop",
        enquiry_id=row["id"],
        operator_principal="alice-key-1",
        expected_version=1,
        include_budget=False,
        now=fixtures.NOW,
    )
    db.commit()
    preview = read(db)
    assert preview["body"] == changed["message"]["body"]
    assert preview["draft_artifact"] == changed["draft_artifact"]
    assert preview["draft_version"] == 2
    assert preview["enquiry_id"] == row["id"]
    assert "AUD 1500.00" not in preview["body"]
    assert preview["requested_quantity"] == 30 and preview["shortfall"] == 15
    assert preview["dispatch_authorized"] is False
    assert db.execute(text("SELECT COUNT(*) FROM outbound_message")).scalar_one() == 0


def test_chat_read_keeps_a_current_initial_saved_draft_without_creating_a_version(db):
    row = prepare(db)
    preview = read(db)
    assert preview["body"] == row["draft_artifact"]["body"]
    assert preview["draft_version"] == 1
    assert preview["dispatch_authorized"] is False
    assert db.execute(text("SELECT COUNT(*) FROM supplier_enquiry_draft")).scalar_one() == 1
    assert db.execute(text("SELECT approval_id FROM supplier_enquiry_request")).scalar_one() is None


def test_multiple_enquiries_require_selection_instead_of_choosing_the_latest(db):
    prepare(db)
    journey.create(
        db,
        tenant_id="shop",
        case_id="case",
        expected_revision=2,
        requester_principal="alice-key-1",
        supplier_ref="other-fictional-supplier",
        source_reference="rfq2",
        recipient_resolver=lambda ref: "other@fixture.invalid",
        now=fixtures.NOW,
    )
    db.commit()
    preview = read(db)
    assert preview["status"] == "draft_selection_required"
    assert preview["missing_inputs"] == ["supplier_enquiry_selection"]
    assert preview.get("draft_artifact") is None
    assert preview["dispatch_authorized"] is False


@pytest.mark.parametrize(
    "tenant,buyer", [("other-controller", "owned-buyer"), ("shop", "other-buyer")]
)
def test_saved_supplier_draft_never_crosses_controller_or_buyer(db, tenant, buyer):
    prepare(db)
    with pytest.raises(ValueError, match="case_task_not_owned"):
        read(db, tenant=tenant, buyer=buyer)


@pytest.mark.parametrize(
    "payload",
    [
        json.dumps({"body": "PRIVATE-TAMPER-CANARY"}),
        "[]",
        "null",
        json.dumps("PRIVATE-TAMPER-CANARY"),
        "{ PRIVATE-TAMPER-CANARY",
    ],
)
def test_tampered_saved_content_is_not_hidden_by_generating_a_new_draft(db, payload):
    prepare(db)
    db.execute(text("UPDATE supplier_enquiry_draft SET draft_json=:value"), {"value": payload})
    db.commit()
    preview = read(db)
    assert preview["status"] == "draft_unavailable"
    assert preview["missing_inputs"] == ["saved_draft_review"]
    assert "PRIVATE-TAMPER-CANARY" not in json.dumps(preview)
    assert preview.get("draft_artifact") is None
    assert preview["dispatch_authorized"] is False


def test_expired_stock_coverage_requires_a_fresh_review_of_the_saved_draft(db):
    prepare(db)
    db.execute(text("UPDATE inventory_reservation SET expires_at='2000-01-01T00:00:00+00:00'"))
    db.commit()
    preview = read(db)
    assert preview["status"] == "draft_stale"
    assert preview["missing_inputs"] == ["current_accepted_selection"]
    assert preview.get("draft_artifact") is None
    assert preview["dispatch_authorized"] is False
