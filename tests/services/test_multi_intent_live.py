"""Tests for the live-flow adapter that bridges the P0 planner into chat (multi_intent_live).

Covers the pure pieces (row shaping + the injected catalog search_fn) and the planner integration on the
exact mixed-turn scenario, DB-free. plan_live's DB read is exercised by the live curl pass; here we lock the
category isolation, scoped-budget filtering, quantity amendment, and the no-cross-contamination invariant so
a regression in any of them fails fast.
"""
from src.app.services.multi_intent_live import _make_search_fn, _row_to_result
from src.app.services.multi_intent_planner import plan_turn


def _catalog():
    return [
        _row_to_result("LAP-021", "Northbridge Pro 15 Laptop", 129900, {"category": "laptop"}),
        _row_to_result("HS-01", "Aurora Wireless Headset", 8900, {"category": "headset"}),
        _row_to_result("HS-02", "Studio Pro Headphones", 24900, {"category": "headset"}),
        _row_to_result("HDD-01", "1TB Portable Hard Drive", 6900, {"category": "hard drive"}),
        _row_to_result("HDD-02", "4TB External Hard Drive", 15900, {"category": "hard drive"}),
        _row_to_result("MON-01", '27" 4K Monitor', 39900, {"category": "monitor"}),
    ]


def test_row_to_result_normalises_string_specs():
    # sqlite hands specs back as a JSON string; the adapter must parse it (pg gives a dict).
    r = _row_to_result("X-1", "Widget", 4999, '{"category": "widget", "tags": ["a", "b"]}')
    assert r["price"] == 49.99 and r["category"] == "widget" and r["tags"] == ["a", "b"]


def test_search_fn_isolates_category_and_respects_budget():
    search = _make_search_fn(_catalog(), limit=6)
    # headset query never returns a monitor/laptop (category isolation)
    assert [r["sku"] for r in search("headsets", 500)] == ["HS-01", "HS-02"]
    # scoped budget drops the over-budget hard drive, keeps the under one, cheapest first
    assert [r["sku"] for r in search("hard drives", 120)] == ["HDD-01"]
    # a monitor query does not leak headsets
    assert [r["sku"] for r in search("monitor", 500)] == ["MON-01"]


def test_plan_turn_keeps_laptop_amends_qty_and_scopes_new_lines():
    search = _make_search_fn(_catalog(), limit=6)
    prior = [{"ref": "LAP-021", "category": "laptop", "requested_qty": 20, "name": "Northbridge Pro 15 Laptop"}]
    q = ("nah that's too expensive, actually i need 15 instead. what options for headsets and hard drives? "
         "i have a budget of 1200 for those")
    res = plan_turn(q, prior_lines=prior, search_fn=search)

    laptop = next(l for l in res["plan"] if l.get("ref") == "LAP-021")
    assert laptop["requested_qty"] == 15                     # amended 20 → 15
    assert not laptop.get("budget_max")                      # laptop must NOT inherit the $1200 scope

    new_lines = [l for l in res["plan"] if l.get("scope") == "new"]
    assert new_lines, "expected new category lines"
    for nl in new_lines:
        assert nl["budget_max"] == 1200
        for r in (nl.get("results") or []):
            assert r["price"] <= 1200                        # every scoped pick within budget

    assert res["verdict"]["ok"] is True                     # adversarial guard clean
    assert res["needs_confirmation"] is True                # money/qty change → confirm, never guess
    assert res["objection_angle"] == "value"                # price objection → value reframe
