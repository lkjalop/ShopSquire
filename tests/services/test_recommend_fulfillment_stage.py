"""Step 6b — the extracted fulfilment stage: availability preserved + flag-gated case creation.

Default behaviour is unchanged (availability set, NO case). With the flag, a real bulk shortfall opens a
durable case advanced to GATE 1 (AWAITING_BUYER_COMMITMENT) and exposes a buyer-safe summary.
"""
from __future__ import annotations

import pytest
from contextlib import contextmanager

from src.app.services import recommend_fulfillment_stage as stage


@pytest.fixture(autouse=True)
def _stub_availability(monkeypatch):
    # deterministic availability so the stage logic is tested without the inventory DB
    monkeypatch.setattr("src.app.services.availability_agent.assess_availability",
                        lambda skus, qty, horizon, draft_reorder=False: {
                            "applicable": True, "sku": skus[0], "requested_qty": qty,
                            "in_stock": 4, "shortfall": max(0, qty - 4)})
    monkeypatch.setattr("src.app.services.availability_agent.availability_summary_line",
                        lambda avail: f"{avail['in_stock']} of {avail['requested_qty']} now")


def _run(flags, qty=10, results=None):
    payload = {}
    line = stage.run_fulfillment_stage(
        results=results if results is not None else [{"sku": "SKU-1"}],
        constraints={"order_quantity": qty}, payload=payload, uid="u1", trace_id="T1", flags=flags)
    return payload, line


def test_availability_preserved_default_no_case():
    payload, line = _run(flags={})
    assert payload["availability"]["shortfall"] == 6 and line == "4 of 10 now"
    assert "fulfillment_case" not in payload  # default: no case (parity)


def test_no_order_quantity_returns_empty():
    payload = {}
    assert stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}], constraints={}, payload=payload, flags={}) == ""
    assert "availability" not in payload


def test_wants_sourcing_detects_reorder_language():
    assert stage._wants_sourcing("reorder 50 gaming laptops from a supplier")
    assert stage._wants_sourcing("please restock 30 monitors")
    assert stage._wants_sourcing("procure 20 keyboards") and stage._wants_sourcing("bulk order 40 headsets")
    assert not stage._wants_sourcing("show me 50 gaming laptops under $2000")  # plain shopping, not sourcing
    assert not stage._wants_sourcing("")


def test_availability_line_names_the_top_pick():
    # §5: for a generic bulk browse the availability is assessed against the TOP pick — the line must NAME it
    # (not imply "we have N of the thing you want" before the buyer has chosen a product).
    avail = {"requested_qty": 20, "network": {"preferred_qty": 3, "fillable_from_network": True,
             "transfer_plan": [{"from_location": "warehouse", "qty": 17}]}}
    named = stage._network_adjusted_availability_line("base", avail, primary_name="HP Envy x360")
    assert named.startswith("For the top match, HP Envy x360:") and "20 units are available" in named
    # no name → falls back to the neutral phrasing (never crashes)
    anon = stage._network_adjusted_availability_line("base", avail, primary_name=None)
    assert anon.startswith("On availability:")


def test_force_sourcing_emits_preview_even_when_in_stock():
    # 'reorder 50 from a supplier' but stock covers it (shortfall 0) → still emit the sourcing preview, sourcing
    # the FULL requested qty (a B2B replenishment isn't gated on retail stock). Closes the unreliable-trigger bug.
    payload = {}
    stage._maybe_open_case(payload=payload, avail={"sku": "GAM-1", "shortfall": 0, "in_stock": 80},
                           order_qty=50, uid="u1", uid_hash=None, trace_id=None,
                           flags={"FULFILLMENT_CASES_ENABLED": True}, defer=True, force_sourcing=True)
    si = payload.get("sourcing_intent")
    assert si and si["mode"] == "deferred_to_cart"
    assert si["lines"][0]["item_ref"] == "GAM-1" and si["lines"][0]["shortfall"] == 50  # source the full 50


def test_in_stock_without_reorder_intent_emits_no_preview():
    payload = {}
    stage._maybe_open_case(payload=payload, avail={"sku": "GAM-1", "shortfall": 0, "in_stock": 80},
                           order_qty=50, uid="u1", uid_hash=None, trace_id=None,
                           flags={"FULFILLMENT_CASES_ENABLED": True}, defer=True, force_sourcing=False)
    assert "sourcing_intent" not in payload   # in stock + no reorder intent → nothing to procure (parity)


def test_pr_id_lands_on_the_sourcing_preview():
    # the deferred (fluid) preview must carry the stable PR id so an amendment re-confirms onto the SAME order.
    payload = {}
    stage.run_fulfillment_stage(
        results=[{"sku": "SKU-1"}], constraints={"order_quantity": 10}, payload=payload, uid="u1",
        trace_id="T1", pr_id="PR-default-20260630-abc12345",
        flags={"FULFILLMENT_CASES_ENABLED": True, "FULFILLMENT_DEFER_TO_CART": True})
    si = payload.get("sourcing_intent") or {}
    assert si.get("mode") == "deferred_to_cart" and si.get("pr_id") == "PR-default-20260630-abc12345"


def test_flag_on_bulk_shortfall_opens_case_at_gate1():
    payload, _line = _run(flags={"FULFILLMENT_CASES_ENABLED": True}, qty=10)
    fc = payload.get("fulfillment_case")
    assert fc and fc["status"] == "awaiting_buyer_commitment" and fc["shortfall"] == 6
    # the durable case really exists and waits at GATE 1
    from src.app.models.db import db_session
    from src.app.services.fulfillment import workflow as fwf
    from src.app.services.fulfillment.domain import FulfillmentState as S
    with db_session() as db:
        assert fwf.current_state(db, fc["case_id"]) == S.AWAITING_BUYER_COMMITMENT
    # buyer-safe summary only — no supplier-private data leaked into the recommend payload
    assert set(fc.keys()) <= {"case_id", "status", "item_ref", "shortfall"}


def test_flag_on_but_no_shortfall_opens_no_case():
    payload, _ = _run(flags={"FULFILLMENT_CASES_ENABLED": True}, qty=4)  # 4 requested, 4 in stock → no shortfall
    assert "fulfillment_case" not in payload


def test_flag_on_below_threshold_opens_no_case():
    payload, _ = _run(flags={"FULFILLMENT_CASES_ENABLED": True, "FULFILLMENT_BULK_THRESHOLD": 50}, qty=10)
    assert "fulfillment_case" not in payload  # 10 < 50 threshold


# ── single-item out-of-stock ("do you have X?" → "no, we can source it") ──────
def test_single_item_oos_opens_case(monkeypatch):
    monkeypatch.setattr("src.app.services.availability_agent.assess_availability",
                        lambda skus, qty, horizon, draft_reorder=False: {
                            "applicable": True, "sku": skus[0], "requested_qty": qty,
                            "in_stock": 0, "shortfall": qty})  # fully out of stock
    payload = {}
    stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}], constraints={"availability_intent": True},
                                payload=payload, uid="u1", trace_id="T1",
                                flags={"FULFILLMENT_CASES_ENABLED": True, "FULFILLMENT_SINGLE_ITEM_OOS": True})
    fc = payload.get("fulfillment_case")
    assert fc and fc["status"] == "awaiting_buyer_commitment" and fc["shortfall"] == 1


def test_single_item_oos_disabled_by_default():
    # availability intent present, but the single-item flag is OFF → no availability, no case (parity)
    payload = {}
    line = stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}], constraints={"availability_intent": True},
                                       payload=payload, flags={"FULFILLMENT_CASES_ENABLED": True})
    assert line == "" and "availability" not in payload and "fulfillment_case" not in payload


def test_single_item_in_stock_opens_no_case(monkeypatch):
    monkeypatch.setattr("src.app.services.availability_agent.assess_availability",
                        lambda skus, qty, horizon, draft_reorder=False: {
                            "applicable": True, "sku": skus[0], "requested_qty": qty,
                            "in_stock": 3, "shortfall": 0})  # we have it
    payload = {}
    stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}], constraints={"availability_intent": True},
                                payload=payload,
                                flags={"FULFILLMENT_CASES_ENABLED": True, "FULFILLMENT_SINGLE_ITEM_OOS": True})
    assert "fulfillment_case" not in payload  # in stock → no procurement


def test_buyer_requirements_captures_constraints_and_keeps_budget_internal():
    # way-1: the buyer's stated constraints are captured on the case for the supplier RFQ. Budget is
    # persisted but flagged internal — the RFQ renderer must never put it in the supplier body.
    from src.app.services.recommend_fulfillment_stage import _buyer_requirements
    r = _buyer_requirements({"use_case": "office", "specs": ["16gb ram", "ssd"],
                             "budget_min": 1300, "budget_max": 1500, "availability_horizon_days": 14})
    assert r["use_case"] == "office"
    assert r["specs"] == ["16gb ram", "ssd"]
    assert r["needed_within_days"] == 14
    assert r["budget"] == {"min": 1300, "max": 1500}
    assert _buyer_requirements({}) == {}  # nothing stated → no requirements


def test_network_breakdown_merged_onto_availability(monkeypatch):
    # multi-location view (per-location stock + transfer plan) is merged onto payload['availability'].
    monkeypatch.setattr(
        "src.app.services.multi_location_availability.assess_network_availability",
        lambda db, skus, qty, preferred_location=None, **kw: {
            "applicable": True, "total_in_network": 17, "by_location": {"sydney": 5, "melbourne": 12},
            "preferred_location": preferred_location, "preferred_qty": 5,
            "transfer_plan": [{"from_location": "melbourne", "qty": 5}],
            "fillable_from_network": True, "shortfall": 0})
    payload = {}
    line = stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}],
                                       constraints={"order_quantity": 10, "ship_to": "sydney"},
                                       payload=payload, uid="u1", trace_id="T1", flags={})
    net = payload["availability"]["network"]
    assert net["total_in_network"] == 17 and net["preferred_location"] == "sydney"
    assert net["transfer_plan"] == [{"from_location": "melbourne", "qty": 5}]
    assert line == "On availability: 10 are available across the network; 5 at your preferred location now and 5 can transfer from other locations."


def test_bulk_alternatives_attached_on_shortfall(monkeypatch):
    # availability stub gives a shortfall; substitutes stubbed → payload['fulfillment_options'] built
    monkeypatch.setattr(
        "src.app.services.multi_location_availability.assess_network_availability",
        lambda db, skus, qty, preferred_location=None, **kw: {
            "applicable": True, "total_in_network": 4, "by_location": {"sydney": 4},
            "preferred_location": preferred_location, "preferred_qty": 4, "transfer_plan": [],
            "fillable_from_network": False, "shortfall": 6})
    monkeypatch.setattr(
        "src.app.services.substitute_generator.find_substitutes",
        lambda db, sku, **kw: [{"sku": "ALT-A", "name": "Alt A", "tradeoff": "$50 more; 2/2 key specs",
                                "price_cents": 155000, "spec_match": 2, "spec_total": 2}])
    payload = {}
    stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}],
                                constraints={"order_quantity": 10, "availability_horizon_days": 10},
                                payload=payload, uid="u1", trace_id="T1", flags={})
    opts = payload.get("fulfillment_options") or []
    types = {o["type"] for o in opts}
    assert "source_shortfall" in types and "substitute" in types  # supplier path + the alternative
    assert "fulfillment_case" not in payload  # flag off → still no case (alternatives are pre-commitment)


def test_recommend_market_action_maps_findings_to_bounded_actions():
    """The market-intelligence step's recommendation is DETERMINISTIC + explainable (no LLM). Each finding
    type maps to a bounded, honest action; an empty finding set with a shortfall still recommends sourcing;
    a truly empty context is honest about internal-only mode. Earns the Market_Intelligence_Agent name."""
    from src.app.services.recommend_fulfillment_stage import _recommend_market_action as rec

    assert "pricing" in rec([{"finding_type": "competitor_undercut"}], {})["action"]
    assert "inventory" in rec([{"finding_type": "demand_shift"}], {})["action"]
    assert "season" in rec([{"finding_type": "seasonal_demand"}], {})["action"].lower()
    # no findings but a real shortfall → still actionable (source it)
    short = rec([], {"shortfall": 6})
    assert "source" in short["action"] and "6" in short["rationale"]
    # nothing at all → HONEST internal-only default, not a fake signal
    empty = rec([], {"shortfall": 0})
    assert "no market action" in empty["action"] and "internal-only" in empty["rationale"]
    # competitor_undercut dominates a co-occurring shortfall (strongest-signal priority)
    assert "pricing" in rec([{"finding_type": "competitor_undercut"}], {"shortfall": 9})["action"]


def test_market_trace_uses_subject_scoped_context_api(monkeypatch):
    """The legacy fulfilment projection must not regress to token-overlap/private helpers."""
    calls = []
    emitted = []

    @contextmanager
    def fake_session():
        yield object()

    def fake_context(db, **kwargs):
        calls.append(kwargs)
        return {"market_findings": [{"finding_type": "demand_shift", "scope": "this_item",
                                      "severity": "warn", "confidence": 0.9,
                                      "summary": "Demand increased."}]}

    monkeypatch.setattr("src.app.models.db.db_session", fake_session)
    monkeypatch.setattr("src.app.services.market_intelligence_agent.gather_market_context", fake_context)
    monkeypatch.setattr(stage, "_emit_trace", lambda *args, **kwargs: emitted.append((args, kwargs)))

    stage._emit_market_intelligence(trace_id="trace-1", query="bulk laptop order",
                                    avail={"sku": "SKU-1", "shortfall": 4})

    assert calls == [{"query": "bulk laptop order", "result_skus": ["SKU-1"],
                      "max_findings": 4, "force": True}]
    assert emitted and emitted[0][0][1] == "market_intelligence_assessed"
    assert emitted[0][0][3]["signals"][0]["scope"] == "this_item"


def test_signal_scope_tiers_this_item_market_related():
    """Tiered MI scoping: exact SKU = this_item; empty/short market labels = market; multi-token
    free-text entities (another query's phrase) = related — the noise class that must not crowd a
    per-SKU procurement card."""
    from src.app.services.recommend_fulfillment_stage import _signal_scope as scope
    assert scope("LAP-1", "LAP-1") == "this_item"
    assert scope("lap-1", "LAP-1") == "this_item"            # case-insensitive
    assert scope(None, "LAP-1") == "market"                   # global finding
    assert scope("search", "LAP-1") == "market"               # short market-level label
    assert scope("google/cpc", "LAP-1") == "market"
    assert scope("can i get help with 15 work laptops", "LAP-1") == "related"   # free-text query entity


def test_sku_specific_action_requires_this_item_signal():
    """An undercut on a DIFFERENT product must not drive a pricing recommendation for this line —
    the action falls through to the demand/shortfall branches instead."""
    from src.app.services.recommend_fulfillment_stage import _recommend_market_action as rec
    other_sku_undercut = [{"finding_type": "competitor_undercut", "scope": "related"},
                          {"finding_type": "demand_shift", "scope": "market"}]
    out = rec(other_sku_undercut, {"shortfall": 5})
    # off-scope undercut does NOT drive pricing; the market-scope demand_shift is off THIS line and
    # carries no upward direction, so it does not trigger inventory expansion either (P0-trust) —
    # the action correctly falls through to the shortfall branch.
    assert "pricing" not in out["action"]
    assert "shortfall" in out["action"].lower()
    this_sku_undercut = [{"finding_type": "competitor_undercut", "scope": "this_item"}]
    assert "pricing" in rec(this_sku_undercut, {})["action"]  # exact-SKU undercut still decisive
    # unscoped findings (legacy/test callers) keep the old behaviour
    assert "pricing" in rec([{"finding_type": "competitor_undercut"}], {})["action"]
