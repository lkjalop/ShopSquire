from datetime import datetime, timezone

from src.app.services.market_action_policy import authorize_replenishment


NOW = datetime(2026, 7, 21, tzinfo=timezone.utc)


def _demand(source):
    return {"scope": "this_item", "direction": "up", "confidence": 0.9,
            "observed_at": "2026-07-20T00:00:00Z", "source_system": source,
            "provenance_chain": [f"{source}/record-1"],
            "tenant_id": "tenant-a", "sku": "SKU-1"}


def _atp(**overrides):
    return {
        "shortfall": 8, "lead_time_days": 12, "confidence": 0.95,
        "observed_at": "2026-07-20T12:00:00Z", "source_system": "wms",
        "provenance_chain": ["wms/snapshot-1"], "tenant_id": "tenant-a", "sku": "SKU-1",
    } | overrides


def _economics(**overrides):
    return {
        "available": True, "clears_floor": True,
        "cost_basis": "validated_landed_supplier_quote",
        "source_record_id": "quote-1", "provenance_chain": ["supplier/quote-1"],
        "tenant_id": "tenant-a", "sku": "SKU-1", "currency": "AUD",
    } | overrides


def test_replenishment_requires_every_independent_gate():
    verdict = authorize_replenishment(
        demand_facts=[_demand("ga4"), _demand("orders")],
        atp=_atp(), economics=_economics(), now=NOW)
    assert verdict["allowed"] is True
    assert verdict["authority"] == "operator_advisory_only"


def test_replenishment_fails_closed_on_one_source_missing_lead_and_fake_margin():
    verdict = authorize_replenishment(
        demand_facts=[_demand("ga4")], atp={"shortfall": 8},
        economics={"available": True, "clears_floor": True,
                   "cost_basis": "demo_estimate"}, now=NOW)
    assert verdict["allowed"] is False
    assert set(verdict["reasons"]) == {
        "insufficient_independent_demand_sources", "missing_supplier_lead_time",
        "untrusted_or_stale_atp", "unverified_or_unprofitable_cost_basis",
    }


def test_replenishment_rejects_stale_or_unproven_atp_and_quote_economics():
    verdict = authorize_replenishment(
        demand_facts=[_demand("ga4"), _demand("orders")],
        atp=_atp(observed_at="2026-07-10T00:00:00Z"),
        economics=_economics(provenance_chain=[]), now=NOW,
    )
    assert verdict["allowed"] is False
    assert set(verdict["reasons"]) == {
        "untrusted_or_stale_atp", "unverified_or_unprofitable_cost_basis",
    }


def test_replenishment_requires_same_tenant_subject_and_currency():
    demand = [_demand("ga4"), _demand("orders")]
    allowed = authorize_replenishment(
        demand_facts=demand, atp=_atp(), economics=_economics(), now=NOW,
        tenant_id="tenant-a", sku="SKU-1", currency="AUD",
    )
    assert allowed["allowed"] is True

    wrong_tenant = authorize_replenishment(
        demand_facts=demand, atp=_atp(tenant_id="tenant-b"), economics=_economics(), now=NOW,
        tenant_id="tenant-a", sku="SKU-1", currency="AUD",
    )
    assert wrong_tenant["allowed"] is False
    assert "untrusted_or_stale_atp" in wrong_tenant["reasons"]

    wrong_subject = authorize_replenishment(
        demand_facts=demand, atp=_atp(), economics=_economics(sku="SKU-2"), now=NOW,
        tenant_id="tenant-a", sku="SKU-1", currency="AUD",
    )
    assert wrong_subject["allowed"] is False
    assert "unverified_or_unprofitable_cost_basis" in wrong_subject["reasons"]

    wrong_currency = authorize_replenishment(
        demand_facts=demand, atp=_atp(), economics=_economics(currency="USD"), now=NOW,
        tenant_id="tenant-a", sku="SKU-1", currency="AUD",
    )
    assert wrong_currency["allowed"] is False
    assert "unverified_or_unprofitable_cost_basis" in wrong_currency["reasons"]


def test_mismatched_demand_cannot_satisfy_source_diversity():
    other_sku = _demand("ga4") | {"sku": "SKU-2"}
    verdict = authorize_replenishment(
        demand_facts=[_demand("orders"), other_sku], atp=_atp(), economics=_economics(), now=NOW,
        tenant_id="tenant-a", sku="SKU-1", currency="AUD",
    )
    assert verdict["allowed"] is False
    assert verdict["demand_source_count"] == 1
    assert "insufficient_independent_demand_sources" in verdict["reasons"]
