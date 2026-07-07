"""R2 — plan-driven evidence scatter-gather. Leg fns injected (no LLM/db needed for the core);
the intelligence under test is SELECTION (plan decides the fan-out) + bounded gathering."""
from __future__ import annotations

import time

from src.app.services.evidence_orchestrator import gather_evidence, select_legs


class _Plan:
    def __init__(self, **kw):
        self.intent = kw.get("intent", "product_search")
        self.needs_market_evidence = kw.get("needs_market_evidence", False)
        self.quantity = kw.get("quantity")
        self.availability_horizon_days = kw.get("availability_horizon_days")
        self.category = kw.get("category")


def _leg(name, found=True, summary="s"):
    def fn(plan, query, uid, **kw):
        return {"source": name, "found": found, "summary": summary, "data": {}}
    return fn


# ── selection: the plan decides the fan-out ──────────────────────────────────

def test_simple_search_selects_nothing():
    assert select_legs(_Plan(), query="gaming laptop under 2000") == []


def test_market_leg_from_plan_signal():
    assert "market" in select_legs(_Plan(needs_market_evidence=True), query="are these prices competitive")


def test_bulk_quantity_selects_availability():
    assert "availability" in select_legs(_Plan(quantity=20), query="need 20 laptops")


def test_support_selects_policy_and_history_with_uid():
    legs = select_legs(_Plan(intent="support"), query="warranty on my laptop", uid="u1")
    assert "policy" in legs and "purchase_history" in legs


def test_no_uid_no_history_leg():
    legs = select_legs(_Plan(intent="support"), query="warranty question", uid=None)
    assert "purchase_history" not in legs


def test_reorder_phrase_selects_history():
    assert "purchase_history" in select_legs(_Plan(), query="same as i bought last time", uid="u1")


def test_image_identity_selects_image_leg():
    legs = select_legs(_Plan(), query="like this but cheaper",
                       image_identity={"brand": "Lenovo", "category": "laptop"})
    assert "image" in legs


# ── gathering: bounded, labeled, failure-visible ─────────────────────────────

def test_gather_runs_selected_legs_and_builds_citations():
    plan = _Plan(intent="support", quantity=5)
    fns = {"policy": _leg("store_policy", summary="30-day returns"),
           "availability": _leg("inventory", summary="9 products, 400 units"),
           "purchase_history": _leg("purchase_history", found=False, summary="")}
    ev = gather_evidence(plan, query="warranty for 5 units", uid="u1", leg_fns=fns)
    assert set(ev["selected"]) == {"policy", "availability", "purchase_history"}
    assert ev["legs"]["policy"]["found"] is True
    # citations only from FOUND legs with a summary
    assert {c["source"] for c in ev["citations"]} == {"store_policy", "inventory"}


def test_gather_empty_selection_is_cheap_noop():
    ev = gather_evidence(_Plan(), query="gaming laptop")
    assert ev["selected"] == [] and ev["legs"] == {} and ev["citations"] == []


def test_hung_leg_times_out_and_reports_not_blocks():
    def hang(plan, query, uid, **kw):
        time.sleep(5)
        return {"source": "market", "found": True, "summary": "late", "data": {}}
    plan = _Plan(needs_market_evidence=True, quantity=3)
    fns = {"market": hang, "availability": _leg("inventory")}
    t0 = time.time()
    ev = gather_evidence(plan, query="bulk price check", leg_fns=fns, budget_s=0.5)
    assert time.time() - t0 < 3.0                       # the hang did NOT block the turn
    assert ev["legs"]["market"].get("error", "").startswith("leg_timeout")
    assert ev["legs"]["availability"]["found"] is True   # the healthy leg still landed


def test_broken_leg_reports_error_never_raises():
    def boom(plan, query, uid, **kw):
        raise RuntimeError("db exploded")
    ev = gather_evidence(_Plan(needs_market_evidence=True), query="price check",
                         leg_fns={"market": boom})
    assert ev["legs"]["market"]["found"] is False
    assert "db exploded" in ev["legs"]["market"]["error"]
