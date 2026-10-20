"""Explicit stock choices update the same buyer intent read by ordinary chat."""
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.models.db import get_engine
from src.app.models.orm import ShoppingCase
from src.app.services.conversation_case_state import ensure_case_state
from src.app.services.shopping_case_supplier_continuation import select_fulfillment_option


@pytest.fixture
def case():
    case_id = "intent-" + uuid.uuid4().hex
    with get_engine().connect() as connection:
        transaction = connection.begin()
        try:
            # Exercise the public committing API while the fixture owns the
            # outer transaction and rolls back only its own isolated rows.
            with Session(connection, join_transaction_mode="rollback_only") as db:
                db.add(ShoppingCase(case_id=case_id, tenant_id="memory-fixture", uid="buyer",
                                    revision=1, retained_purpose="Fictional workload", status="active"))
                db.flush()
                ensure_case_state(db, tenant_id="memory-fixture", case_id=case_id, session_epoch="epoch",
                    subject_ref="subject", commit=False, authoritative_anchor={
                        "requested_quantity": 1, "sku": "OLD", "objective": "Fictional workload",
                        "budget": {"amount_minor": 500000, "currency": "AUD", "scope": "per_unit"}})
                yield db, case_id
        finally:
            transaction.rollback()



def _select(db, case_id, quantity):
    return select_fulfillment_option(db, tenant_id="memory-fixture", case_id=case_id, uid="buyer",
        expected_revision=1, choice="split_delivery", preferred_sku="NEW",
        requested_quantity=quantity, available_now=min(quantity, 25),
        idempotency_key="choice", offers=[], use_canonical_case_revision=True)


def _stored(db, case_id):
    row = db.execute(text("SELECT version,state_json FROM conversation_case_state "
        "WHERE tenant_id='memory-fixture' AND case_id=:case"), {"case": case_id}).one()
    return row[0], json.loads(row[1])["procurement_case_state"]


@pytest.mark.parametrize("quantity", [40, 12])
def test_stock_choice_preserves_budget_and_updates_canonical_quantity_and_sku(case, quantity):
    db, case_id = case
    selected, error = _select(db, case_id, quantity)
    assert error is None
    revision, state = _stored(db, case_id)
    assert state["requested_quantity"] == quantity
    assert state["selected_sku"] == "NEW"
    assert revision == state["revision"] == selected.revision == 2
    assert state["budget"] == {"amount_minor": 500000, "currency": "AUD", "scope": "per_unit"}


def test_stock_choice_cannot_silently_discard_existing_destination_allocation(case):
    db, case_id = case
    row = db.execute(text("SELECT state_json FROM conversation_case_state WHERE case_id=:case"),
                     {"case": case_id}).scalar_one()
    state = json.loads(row)
    state["procurement_case_state"]["destinations"] = [
        {"location_ref": "Sydney", "location_kind": "city", "quantity": 1}]
    db.execute(text("UPDATE conversation_case_state SET state_json=:state WHERE case_id=:case"),
               {"state": json.dumps(state), "case": case_id})
    with pytest.raises(ValueError, match="destination_quantity_total_mismatch"):
        with db.begin_nested():
            _select(db, case_id, 40)
    revision, unchanged = _stored(db, case_id)
    assert revision == unchanged["revision"] == 1
    assert unchanged["requested_quantity"] == 1
    assert unchanged["destinations"][0]["quantity"] == 1
