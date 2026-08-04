"""P0-trust: the market-intelligence action must not recommend "secure inventory ahead of demand"
on a bare demand_shift finding — a demand_shift can be a SLOWDOWN. The trace was recommending
inventory expansion while its own signals said demand was slowing (self-contradiction on a
trust-layer). Inventory expansion now requires UPWARD demand (evidence.direction) AND insufficient
ATP (a real shortfall)."""
from __future__ import annotations

from src.app.services.recommend_fulfillment_stage import _recommend_market_action


def _f(ftype, direction=None, scope="this_item", summary=""):
    return {"finding_type": ftype, "scope": scope, "summary": summary,
            "evidence": ({"direction": direction} if direction else {})}


def test_downward_demand_shift_does_not_recommend_expansion():
    rec = _recommend_market_action(
        [_f("demand_shift", "slowdown", summary="Search demand slowdown vs baseline")], {"shortfall": 0})
    assert "secure inventory ahead of demand" not in rec["action"], rec


def test_upward_demand_with_shortfall_only_sources_verified_deficit_without_governed_economics():
    rec = _recommend_market_action(
        [_f("demand_shift", "spike", summary="Search demand spike vs baseline")], {"shortfall": 5})
    assert rec["action"] == "source the verified shortfall", rec
    assert rec["policy"]["allowed"] is False


def test_upward_demand_without_shortfall_no_expansion():
    # rising demand but ATP is sufficient (no shortfall) -> no proactive expansion
    rec = _recommend_market_action([_f("demand_shift", "spike")], {"shortfall": 0})
    assert "secure inventory ahead of demand" not in rec["action"], rec


def test_downward_demand_with_shortfall_sources_shortfall_not_expansion():
    rec = _recommend_market_action([_f("demand_shift", "slowdown")], {"shortfall": 5})
    assert "secure inventory ahead of demand" not in rec["action"], rec
    assert "shortfall" in rec["action"].lower(), rec
