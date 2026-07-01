"""Scatter-gather adversarial guard — verify an assembled multi-line plan. Agnostic, pure, fail-closed."""
from __future__ import annotations

from src.app.services import scatter_gather_guard as g


def _laptop_line():
    return {"ref": "LAP-1", "category": "laptops", "scope": "prior", "requested_qty": 15,
            "budget_max": None, "results": [{"name": "MSI Katana Laptop", "price_cents": 180000}]}


def _clean_plan():
    return [
        _laptop_line(),
        {"category": "headsets", "scope": "new", "budget_max": 1200,
         "results": [{"name": "SteelSeries Gaming Headset", "price_cents": 12900}]},
        {"category": "hard drives", "scope": "new", "budget_max": 1200,
         "results": [{"name": "Samsung 2TB Hard Drive", "price_cents": 9900}]},
    ]


def test_clean_plan_passes():
    v = g.verify_plan(_clean_plan(), must_survive=["LAP-1"])
    assert v.ok and v.violations == [] and v.checked_lines == 3


def test_category_mismatch_flagged():
    plan = _clean_plan()
    plan[1]["results"] = [{"name": "MSI Katana Laptop", "price_cents": 180000}]   # laptop in a headset line
    v = g.verify_plan(plan, must_survive=["LAP-1"])
    assert not v.ok and any("category mismatch" in x for x in v.violations)


def test_budget_bleed_flagged():
    plan = _clean_plan()
    plan[1]["results"] = [{"name": "Premium Headset", "price_cents": 150000}]   # $1500 > $1200 scope
    v = g.verify_plan(plan)
    assert not v.ok and any("budget bleed" in x for x in v.violations)


def test_quantity_out_of_range_flagged():
    plan = _clean_plan()
    plan[0]["requested_qty"] = 1500
    v = g.verify_plan(plan)
    assert not v.ok and any("quantity out of range" in x for x in v.violations)


def test_context_lost_flagged():
    plan = [l for l in _clean_plan() if l.get("ref") != "LAP-1"]   # laptop dropped
    v = g.verify_plan(plan, must_survive=["LAP-1"])
    assert not v.ok and any("context lost" in x for x in v.violations)


def test_cross_contamination_flagged():
    plan = _clean_plan()
    plan[0]["budget_max"] = 1200   # the new scoped $1200 leaked onto the prior laptop line
    v = g.verify_plan(plan, must_survive=["LAP-1"])
    assert not v.ok and any("cross-contamination" in x for x in v.violations)


def test_empty_category_is_vacuously_ok():
    v = g.verify_plan([{"category": "", "scope": "new", "results": [{"name": "anything", "price_cents": 100}]}])
    assert v.ok


def test_multiple_violations_all_reported():
    plan = _clean_plan()
    plan[0]["requested_qty"] = 9999
    plan[1]["results"] = [{"name": "A Laptop", "price_cents": 300000}]   # mismatch + bleed
    v = g.verify_plan(plan, must_survive=["MISSING"])
    assert not v.ok and len(v.violations) >= 3   # qty + category + bleed + context
