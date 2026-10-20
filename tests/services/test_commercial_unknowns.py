"""Unknown commercial inputs must not become satisfied buyer constraints."""
import pytest

from src.app.services.commercial_decision_reducer import reduce_commercial_candidate
from tests.services.test_commercial_decision_reducer import candidate


@pytest.mark.parametrize("supplier,lead", [(None, None), (0, None), (10, 2)])
def test_unknown_local_stock_cannot_establish_a_shortfall_or_late_delivery(supplier, lead):
    decision = reduce_commercial_candidate(candidate(local_available_now=None,
        supplier_quantity=supplier, supplier_lead_time_days=lead))
    assert decision.quantity_outcome == "unknown"
    assert decision.shortfall is None
    assert decision.available_by_deadline is None
    assert decision.status == "UNVERIFIED"
    assert "unverified" in " ".join(decision.reasons).lower()
    assert decision.cart_authority == decision.supplier_send_authority == "none"


def test_supplier_alone_can_prove_sufficient_supply_without_inventing_local_stock():
    decision = reduce_commercial_candidate(candidate(local_available_now=None,
        supplier_quantity=30, supplier_lead_time_days=2))
    assert decision.quantity_outcome == "complete_by_deadline"
    assert decision.available_by_deadline == 30
    assert decision.shortfall == 0


@pytest.mark.parametrize("budget", [600000, None])
def test_missing_price_cannot_be_within_budget_or_commercially_qualified(budget):
    decision = reduce_commercial_candidate(candidate(unit_price_cents=None, budget_per_unit_cents=budget))
    assert decision.budget_outcome == ("unknown" if budget is not None else "not_stated")
    assert decision.status == "UNVERIFIED"
    assert decision.fit_tier == "qualified"
    assert "price" in " ".join(decision.reasons).lower()


def test_missing_budget_is_explicit_in_explanation():
    decision = reduce_commercial_candidate(candidate(budget_per_unit_cents=None))
    assert decision.budget_outcome == "not_stated"
    assert "no budget" in " ".join(decision.reasons).lower()


@pytest.mark.parametrize("changes,expected_fit", [
    ({"exact_identity": False}, "unverified"),
    ({"material_unknowns": ["driver compatibility"]}, "conditional"),
])
def test_over_budget_does_not_promote_unverified_technical_fit(changes, expected_fit):
    decision = reduce_commercial_candidate(candidate(unit_price_cents=610000, **changes))
    assert decision.status == "OVER_BUDGET"
    assert decision.fit_tier == expected_fit


def test_unknown_mandatory_form_factor_remains_conditional():
    decision = reduce_commercial_candidate(candidate(actual_form_factor=None))
    assert decision.fit_tier == "conditional"
    assert decision.status == "CONDITIONAL_NOW"
