from src.app.services.recommendation_core.envelope import ProductCard
from src.app.services.recommendation_core.legacy_card_commercial_projection import (
    project_legacy_card_commercial_decision,
)


def test_legacy_card_uses_canonical_reducer_without_inventing_identity():
    card = ProductCard(
        sku="LAP-1", price_cents=450_000, currency="AUD", stock=3,
        fit={"overall": "meets"},
    )
    result = project_legacy_card_commercial_decision(
        card, budget_per_unit_cents=400_000, requested_quantity=5, deadline_days=3,
    )
    assert result["projection_source"] == "canonical_commercial_reducer"
    assert result["status"] == "OVER_BUDGET"
    assert result["quantity_outcome"] == "partial"
    assert result["ranking_authority_granted"] is False


def test_verified_failure_beats_price_or_stock():
    card = ProductCard(
        sku="EXPENSIVE", price_cents=900_000, currency="AUD", stock=20,
        fit={
            "overall": "fails", "exact_identity": True,
            "specification_freshness": "fresh",
            "per_key": {"vendor_certification": "fails"},
        },
    )
    result = project_legacy_card_commercial_decision(
        card, budget_per_unit_cents=None, requested_quantity=1, deadline_days=None,
    )
    assert result["status"] == "FAILED_REQUIREMENT"
    assert result["fit_tier"] == "failed"
    assert "vendor_certification" in result["reasons"][0]


def test_product_card_serializes_typed_commercial_projection():
    card = ProductCard(sku="LAP-2")
    card.commercial_decision = {"status": "UNVERIFIED"}
    assert card.as_dict()["commercial_decision"] == {"status": "UNVERIFIED"}
