from datetime import datetime, timezone

from src.app.services.executive_metrics import (
    forecast_quality, gmroi_unavailable, inventory_productivity, ppv_evidence,
)


def test_forecast_quality_exposes_wape_bias_and_coverage():
    rows = [
        {"forecast": 12, "actual": 10, "source_record_id": "f1"},
        {"forecast": 8, "actual": 10, "source_record_id": "f2"},
    ]
    metrics = {
        item.metric: item for item in forecast_quality(
            tenant_id="tenant-a", subject_id="SKU-1", observations=rows,
            as_of=datetime(2026, 7, 24, tzinfo=timezone.utc))
    }
    assert metrics["forecast_wape"].value == 0.2
    assert metrics["forecast_bias"].value == 0.0
    assert metrics["forecast_coverage"].value == 1.0
    assert all(item.status == "observed" for item in metrics.values())


def test_inventory_productivity_is_explicitly_estimated_from_point_atp():
    metrics = inventory_productivity(
        tenant_id="tenant-a", sku="SKU-1", units_sold=30, window_days=30,
        available_units=14, source_records=["orders/o1", "wms/a1"])
    assert {item.metric for item in metrics} == {"weeks_of_supply", "inventory_turns"}
    assert all(item.status == "estimated" for item in metrics)
    assert all(item.metadata["inventory_basis"] == "current_atp_not_average_inventory"
               for item in metrics)


def test_ppv_requires_matched_quote_po_invoice_identity():
    unavailable = ppv_evidence(
        tenant_id="tenant-a", sku="SKU-1",
        quote={"match_id": "A", "currency": "AUD", "unit_cost_cents": 100},
        purchase_order={"match_id": "A", "currency": "AUD", "unit_cost_cents": 100},
        invoice={"match_id": "B", "currency": "AUD", "unit_cost_cents": 110})
    assert unavailable.status == "unavailable"
    observed = ppv_evidence(
        tenant_id="tenant-a", sku="SKU-1",
        quote={"match_id": "A", "currency": "AUD", "unit_cost_cents": 100,
               "provenance": "quote/A"},
        purchase_order={"match_id": "A", "currency": "AUD", "unit_cost_cents": 100,
                        "provenance": "po/A"},
        invoice={"match_id": "A", "currency": "AUD", "unit_cost_cents": 110,
                 "provenance": "invoice/A"})
    assert observed.status == "observed"
    assert observed.value == 10


def test_gmroi_remains_unavailable_without_average_landed_cost_inventory():
    metric = gmroi_unavailable(tenant_id="tenant-a", subject_id="SKU-1")
    assert metric.status == "unavailable"
    assert metric.reason == "average_landed_cost_inventory_valuation_required"
