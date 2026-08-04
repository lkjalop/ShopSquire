from datetime import datetime, timezone

import pytest

from src.app.services.executive_metrics import (
    compare_forecast_candidates, forecast_quality, gmroi_unavailable,
    inventory_productivity, ppv_evidence,
)

_FIXED = datetime(2026, 7, 24, tzinfo=timezone.utc)


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


def test_forecast_challenger_reports_quality_and_monetary_impact_without_promoting():
    result = compare_forecast_candidates(
        tenant_id="tenant-a", subject_id="SKU-1",
        baseline=[{"forecast": 20, "actual": 10, "source_record_id": "b1"}],
        challenger=[{"forecast": 12, "actual": 10, "source_record_id": "c1"}],
        unit_value_cents=5000, as_of=_FIXED,
    )

    assert result["recommendation"] == "challenger_better"
    assert result["wape_improvement"] == pytest.approx(0.8)
    assert result["estimated_absolute_error_value_cents"] == 40000
    assert result["authority"] == "shadow_evaluation_only"


def test_inventory_productivity_is_explicitly_estimated_from_point_atp():
    metrics = inventory_productivity(
        tenant_id="tenant-a", sku="SKU-1", units_sold=30, window_days=30,
        available_units=14, source_records=["orders/o1", "wms/a1"])
    assert {item.metric for item in metrics} == {"weeks_of_supply", "inventory_turns"}
    assert all(item.status == "estimated" for item in metrics)
    assert all(item.metadata["inventory_basis"] == "current_atp_not_average_inventory"
               for item in metrics)


def test_zero_atp_is_stockout_wos_but_not_an_inventory_turns_denominator():
    metrics = {
        item.metric: item for item in inventory_productivity(
            tenant_id="tenant-a", sku="SKU-1", units_sold=30, window_days=30,
            available_units=0, source_records=["orders/o1", "wms/a1"])
    }

    assert metrics["weeks_of_supply"].value == 0
    assert metrics["weeks_of_supply"].status == "estimated"
    assert metrics["inventory_turns"].value is None
    assert metrics["inventory_turns"].status == "insufficient_data"
    assert metrics["inventory_turns"].reason == "zero_current_atp_denominator"


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


# ── invariants (stakeholder guarantees, example-based property tests) ─────────

@pytest.mark.parametrize("units_sold,window_days,available_units", [
    (0, 30, 0), (1, 30, 1), (30, 30, 14), (500, 7, 3), (5, 90, 200),
    (10_000, 1, 1), (3, 45, 0), (250, 30, 999),
])
def test_wos_and_turns_are_never_negative(units_sold, window_days, available_units):
    """CFO/ops invariant: a productivity metric is either >= 0 or explicitly None
    (insufficient) — a negative weeks-of-supply or turns figure is never emitted."""
    for item in inventory_productivity(
        tenant_id="t", sku="S", units_sold=units_sold, window_days=window_days,
        available_units=available_units, source_records=["orders/o1"], as_of=_FIXED):
        if item.value is not None:
            assert item.value >= 0, (item.metric, item.value)
        else:
            assert item.status == "insufficient_data" and item.reason


def test_missing_current_atp_blocks_both_productivity_metrics():
    """Ops invariant: stale/absent ATP must BLOCK action, not estimate around it."""
    metrics = {m.metric: m for m in inventory_productivity(
        tenant_id="t", sku="S", units_sold=30, window_days=30,
        available_units=None, source_records=["orders/o1"], as_of=_FIXED)}
    for name in ("weeks_of_supply", "inventory_turns"):
        assert metrics[name].value is None
        assert metrics[name].status == "insufficient_data"
        assert metrics[name].reason == "missing_current_atp"


@pytest.mark.parametrize("q_ccy,po_ccy,inv_ccy", [
    ("AUD", "AUD", "USD"), ("USD", "AUD", "AUD"), ("AUD", "USD", "EUR"),
])
def test_ppv_never_aggregates_across_currencies(q_ccy, po_ccy, inv_ccy):
    """CFO/security invariant: a matched identity is not enough — mixed currency
    must fall to unavailable, never a cross-currency subtraction."""
    metric = ppv_evidence(
        tenant_id="t", sku="S",
        quote={"match_id": "A", "currency": q_ccy, "unit_cost_cents": 100},
        purchase_order={"match_id": "A", "currency": po_ccy, "unit_cost_cents": 100},
        invoice={"match_id": "A", "currency": inv_ccy, "unit_cost_cents": 110})
    assert metric.status == "unavailable"
    assert metric.value is None


@pytest.mark.parametrize("tenant,subject", [
    ("t1", "S1"), ("t2", "S2"), ("acme", "LAP-1"), ("", "")])
def test_gmroi_is_unconditionally_unavailable(tenant, subject):
    """Unknown landed-cost valuation => GMROI unavailable, for every tenant/subject."""
    metric = gmroi_unavailable(tenant_id=tenant, subject_id=subject)
    assert metric.status == "unavailable" and metric.value is None


def test_productivity_is_deterministic_for_identical_inputs():
    """Duplicate/replayed events must not move a metric: identical inputs =>
    identical values (idempotency at the formula boundary)."""
    kw = dict(tenant_id="t", sku="S", units_sold=30, window_days=30,
              available_units=14, source_records=["orders/o1"], as_of=_FIXED)
    a = {m.metric: (m.value, m.status) for m in inventory_productivity(**kw)}
    b = {m.metric: (m.value, m.status) for m in inventory_productivity(**kw)}
    assert a == b
