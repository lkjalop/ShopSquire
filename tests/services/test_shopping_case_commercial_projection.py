from datetime import datetime, timezone

from src.app.services.shopping_case_commercial_projection import (
    project_case_commercial_decision,
)


def test_shared_reducer_combines_budget_quantity_deadline_and_supplier_offer():
    result = project_case_commercial_decision(
        state_data={
            "selected_sku": "CFG-1",
            "requested_quantity": 30,
            "budget": {"amount_minor": 5_000_000, "currency": "AUD", "scope": "total"},
        },
        fulfilment={
            "available_now": 12,
            "deadline_days": 10,
            "unit_price_cents": 200_000,
            "currency": "AUD",
            "offers": [{
                "offered_sku": "CFG-1",
                "relationship": "exact",
                "quantity_available": 18,
                "lead_time_days": 8,
                "unit_price_cents": 200_000,
                "trust_status": "trusted",
                "response_status": "accepted",
                "validity_expires_at": "2027-01-01T00:00:00+00:00",
            }],
        },
        evaluation_time=datetime(2026, 8, 18, tzinfo=timezone.utc),
    )
    assert result["quantity_outcome"] == "complete_by_deadline"
    assert result["available_by_deadline"] == 30
    assert result["budget_outcome"] == "over"
    assert result["status"] == "OVER_BUDGET"
    assert result["cart_authority"] == "none"


def test_expired_offer_does_not_satisfy_quantity():
    result = project_case_commercial_decision(
        state_data={"selected_sku": "CFG-1", "requested_quantity": 30},
        fulfilment={
            "available_now": 12,
            "deadline_days": 10,
            "offers": [{
                "offered_sku": "CFG-1",
                "relationship": "exact",
                "quantity_available": 18,
                "lead_time_days": 8,
                "trust_status": "trusted",
                "response_status": "accepted",
                "validity_expires_at": "2026-08-17T00:00:00+00:00",
            }],
        },
        evaluation_time=datetime(2026, 8, 18, tzinfo=timezone.utc),
    )
    assert result["quantity_outcome"] == "partial"
    assert result["shortfall"] == 18
    assert result["status"] == "UNVERIFIED"


def test_malformed_offer_validity_fails_closed_instead_of_crashing():
    result = project_case_commercial_decision(
        state_data={"selected_sku": "CFG-1", "requested_quantity": 5},
        fulfilment={
            "available_now": 0,
            "offers": [{
                "offered_sku": "CFG-1",
                "relationship": "exact",
                "quantity_available": 5,
                "lead_time_days": 1,
                "trust_status": "trusted",
                "response_status": "accepted",
                "validity_expires_at": "not-a-time",
            }],
        },
        evaluation_time=datetime(2026, 8, 18, tzinfo=timezone.utc),
    )
    assert result["quantity_outcome"] == "partial"
    assert result["shortfall"] == 5
