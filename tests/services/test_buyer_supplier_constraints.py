from datetime import timedelta
import json
import pytest
from sqlalchemy import text
from tests.services.test_buyer_supplier_selection import db, prepare, choose, NOW
from src.app.services.buyer_supplier_quotes import project_quotes
from src.app.services.buyer_supplier_selection import read_selection


def constraints(db, **values):
    temporal = values.get("temporal")
    if temporal and temporal.get("resolution_status") == "resolved":
        temporal.update(
            resolved_utc_instant=temporal["required_by"],
            interpretation_instant=NOW.isoformat(),
            calendar_source="fixture",
            calendar_version="1",
        )
    db.execute(text("DELETE FROM conversation_case_state"))
    db.execute(
        text(
            "INSERT INTO conversation_case_state "
            "(id,tenant_id,case_id,session_epoch,subject_ref,version,state_json,created_at,updated_at) "
            "VALUES ('constraint','synthetic-shop','case','epoch','buyer',2,:state,:now,:now)"
        ),
        dict(
            state=json.dumps({"procurement_case_state": {"revision": 2, **values}}),
            now=NOW.isoformat(),
        ),
    )


def current(db, now=NOW):
    return project_quotes(db, tenant_id="synthetic-shop", case_id="case", now=now)["quotes"][0]


def test_freight_cannot_push_selected_estimate_past_total_budget(db):
    prepare(db)
    constraints(db, budget={"amount_minor": 3000000, "currency": "AUD", "scope": "total"})
    estimate = current(db)
    assert not estimate["eligible"]
    assert estimate["reason"] == "supplier_estimate_exceeds_total_budget"
    with pytest.raises(ValueError, match="current_reviewed_supplier_quote_required"):
        choose(db, estimate)


@pytest.mark.parametrize(
    "temporal,reason",
    [
        (
            {"original_expression": "soon", "resolution_status": "ambiguous"},
            "delivery_deadline_unresolved",
        ),
        (
            {"required_by": (NOW + timedelta(days=2)).isoformat(), "resolution_status": "resolved"},
            "estimated_delivery_after_deadline",
        ),
    ],
)
def test_unresolved_or_missed_deadline_blocks_selection(db, temporal, reason):
    prepare(db)
    constraints(db, temporal=temporal)
    assert current(db)["reason"] == reason
    assert not current(db)["eligible"]


def test_deadline_revalidation_changes_status_without_moving_digest_every_second(db):
    prepare(db)
    constraints(
        db,
        temporal={
            "required_by": (NOW + timedelta(days=5, minutes=5)).isoformat(),
            "resolution_status": "resolved",
        },
    )
    first = current(db)
    choose(db, first)
    assert first["eligible"]
    assert current(db, NOW + timedelta(minutes=1))["selection_digest"] == first["selection_digest"]
    result = read_selection(
        db, tenant_id="synthetic-shop", case_id="case", uid="buyer", now=NOW + timedelta(minutes=6)
    )
    assert result["status"] == "revalidation_required"


def test_wrong_currency_and_conflicting_revision_are_not_treated_as_unconstrained(db):
    prepare(db)
    constraints(db, budget={"amount_minor": 999999999, "currency": "USD", "scope": "total"})
    assert current(db)["reason"] == "supplier_budget_currency_mismatch"
    db.execute(text("UPDATE conversation_case_state SET version=1"))
    assert current(db)["reason"] == "supplier_requirement_revision_conflict"
