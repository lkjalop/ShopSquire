from src.app.services.commercial_decision_reducer import (
    CommercialCandidate,
    reduce_commercial_candidate,
)


def candidate(**overrides):
    values = {
        "sku": "PREFERRED", "exact_identity": True,
        "actual_form_factor": "laptop", "mandatory_form_factor": "laptop",
        "specification_freshness": "fresh", "unit_price_cents": 590_000,
        "budget_per_unit_cents": 600_000, "requested_quantity": 30,
        "local_available_now": 12, "supplier_quantity": 18,
        "supplier_lead_time_days": 8, "deadline_days": 10,
    }
    values.update(overrides)
    return CommercialCandidate(**values)


def test_exact_split_supply_is_qualified_by_deadline() -> None:
    decision = reduce_commercial_candidate(candidate())
    assert decision.status == "QUALIFIED_NOW"
    assert decision.available_by_deadline == 30
    assert decision.shortfall == 0
    assert decision.cart_authority == "none"


def test_partial_and_late_are_separate_quantity_outcomes() -> None:
    partial = reduce_commercial_candidate(candidate(supplier_quantity=10))
    late = reduce_commercial_candidate(candidate(supplier_quantity=18, supplier_lead_time_days=21))
    assert (partial.status, partial.shortfall) == ("QUALIFIED_PARTIAL", 8)
    assert (late.status, late.quantity_outcome) == ("QUALIFIED_LATE", "late")


def test_expedited_two_day_request_keeps_eight_day_offer_late() -> None:
    decision = reduce_commercial_candidate(candidate(deadline_days=2))
    assert decision.status == "QUALIFIED_LATE"
    assert "after the requested deadline" in " ".join(decision.reasons)


def test_substitute_is_conditional_even_when_cheaper_and_available() -> None:
    decision = reduce_commercial_candidate(candidate(
        sku="SUBSTITUTE", relationship="compatible_substitute",
        unit_price_cents=530_000, local_available_now=0, supplier_quantity=30,
        supplier_lead_time_days=2,
    ))
    assert decision.status == "CONDITIONAL_NOW"
    assert decision.resolution_owner == "buyer"
    assert "explicit buyer acceptance" in " ".join(decision.reasons)


def test_hard_failure_wins_over_price_and_availability() -> None:
    decision = reduce_commercial_candidate(candidate(
        unit_price_cents=300_000, local_available_now=30,
        verified_minimum_misses=["Windows 11 Pro"],
    ))
    assert decision.status == "FAILED_REQUIREMENT"
    assert decision.resolution_owner == "catalog"


def test_budget_and_unverified_states_are_never_silently_qualified() -> None:
    over = reduce_commercial_candidate(candidate(unit_price_cents=610_000))
    unknown = reduce_commercial_candidate(candidate(
        exact_identity=False, unit_price_cents=500_000,
    ))
    assert over.status == "OVER_BUDGET"
    assert unknown.status == "UNVERIFIED"


def test_mandatory_mobility_keeps_workstation_as_architecture_alternative() -> None:
    decision = reduce_commercial_candidate(candidate(
        actual_form_factor="fixed_workstation", local_available_now=30,
    ))
    assert decision.status == "FAILED_REQUIREMENT"
    assert "Mandatory form factor" in " ".join(decision.reasons)
