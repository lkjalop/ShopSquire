from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.app.services.advanced_inventory_intelligence import (
    aggregate_uom_quantities,
    estimate_lost_demand,
    forecast_value_added,
    lot_ageing_report,
    reconcile_hierarchical_forecasts,
    spend_weighted_concentration,
)


def test_lot_ageing_defines_expired_waste_and_preserves_unknown_expiry() -> None:
    result = lot_ageing_report([
        {
            "lot_id": "old", "variant_id": "v1", "location_id": "s1",
            "quantity_remaining": 3, "uom": "EA",
            "expires_at": "2026-01-01T00:00:00Z", "unit_cost_minor": 125,
        },
        {
            "lot_id": "unknown", "variant_id": "v1", "location_id": "s1",
            "quantity_remaining": 2, "uom": "EA", "expires_at": None,
        },
    ], as_of="2026-02-01T00:00:00Z")

    assert result["expired_units"] == 3
    assert result["expired_value_minor"] == 375
    assert result["expiry_completeness"] == {
        "status": "incomplete", "missing_lots": 1,
    }
    assert result["execution_allowed"] is False


def test_multi_uom_aggregation_fails_closed_on_unapproved_conversion() -> None:
    def converter(value, source, target, at_time):
        del at_time
        if (source, target) == ("CASE", "EA"):
            return SimpleNamespace(
                status="comparable", value=value * Decimal("12"),
                authority_id="pack-12", reason=None,
            )
        return SimpleNamespace(
            status="incomparable", value=None, authority_id=None,
            reason="uom_conversion_not_approved",
        )

    comparable = aggregate_uom_quantities(
        [{"quantity": 2, "uom": "CASE"}],
        target_uom="EA", converter=converter, at_time="2026-01-01T00:00:00Z",
    )
    assert comparable["quantity"] == "24"
    assert comparable["conversion_authority_ids"] == ["pack-12"]

    blocked = aggregate_uom_quantities(
        [{"quantity": 2, "uom": "PALLET"}],
        target_uom="EA", converter=converter, at_time="2026-01-01T00:00:00Z",
    )
    assert blocked["status"] == "incomparable"
    assert blocked["quantity"] is None


def test_lost_demand_prefers_latent_attempts_and_labels_estimates() -> None:
    observed = estimate_lost_demand([
        {"latent_demand_units": 8, "fulfilled_units": 5},
        {"latent_demand_units": 4, "fulfilled_units": 4},
    ])
    assert observed["status"] == "observed_latent_attempts"
    assert observed["lost_units"] == 3

    estimated = estimate_lost_demand(
        [{"observed_sales_units": 10, "stockout": False}] * 7
        + [{"observed_sales_units": 2, "stockout": True}]
    )
    assert estimated["status"] == "estimated_stockout_censoring"
    assert estimated["lost_units"] == 8
    assert estimated["authority"] == "shadow_only"


def test_hierarchical_bottom_up_is_coherent_and_rejects_cycles() -> None:
    result = reconcile_hierarchical_forecasts(
        {"sku-a": 3, "sku-b": 7},
        {"sku-a": "category", "sku-b": "category", "category": "total"},
    )
    assert result["forecasts"] == {
        "category": 10.0, "sku-a": 3.0, "sku-b": 7.0, "total": 10.0,
    }
    with pytest.raises(ValueError, match="forecast_hierarchy_cycle"):
        reconcile_hierarchical_forecasts({"a": 1}, {"a": "b", "b": "a"})


def test_fva_and_spend_weighted_concentration_keep_explicit_states() -> None:
    assert forecast_value_added(
        baseline_error=20, candidate_error=15, metric="WAPE",
    )["value"] == 0.25
    assert forecast_value_added(
        baseline_error=0, candidate_error=0, metric="WAPE",
    )["status"] == "undefined_zero_baseline_error"

    concentration = spend_weighted_concentration({"supplier-a": 90, "supplier-b": 10})
    assert concentration["hhi"] == 0.82
    assert concentration["method"] == "spend_weighted_hhi"
