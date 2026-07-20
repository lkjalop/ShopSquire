from datetime import datetime, timezone

from src.app.services.market_action_policy import authorize_replenishment


NOW = datetime(2026, 7, 21, tzinfo=timezone.utc)


def _demand(source):
    return {"scope": "this_item", "direction": "up", "confidence": 0.9,
            "observed_at": "2026-07-20T00:00:00Z", "source_system": source,
            "provenance_chain": [f"{source}/record-1"]}


def test_replenishment_requires_every_independent_gate():
    verdict = authorize_replenishment(
        demand_facts=[_demand("ga4"), _demand("orders")],
        atp={"shortfall": 8, "lead_time_days": 12},
        economics={"available": True, "clears_floor": True,
                   "cost_basis": "validated_landed_supplier_quote"}, now=NOW)
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
        "unverified_or_unprofitable_cost_basis",
    }
