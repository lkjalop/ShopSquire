"""Multi-intent planner — decompose → amend prior qty → scatter-gather new lines → guard. Agnostic, pure."""
from __future__ import annotations

from src.app.services.multi_intent_planner import plan_turn

SCENARIO = ("nah that's too expensive, actually i need 15 instead? what options for headsets and "
            "hard drives. i have a budget for 1200 for those?")

_CATALOG = {
    "headsets": [{"name": "SteelSeries Gaming Headset", "price_cents": 12900}],
    "hard drives": [{"name": "Samsung 2TB Hard Drive", "price_cents": 9900}],
}


def _good_search(category, budget_max):
    rows = _CATALOG.get(category, [])
    return [r for r in rows if budget_max is None or (r["price_cents"] / 100) <= budget_max]


def _laptop_prior():
    return [{"ref": "LAP-1", "category": "laptops", "requested_qty": 20,
             "results": [{"name": "MSI Katana Laptop", "price_cents": 180000}]}]


def test_full_scenario_end_to_end():
    out = plan_turn(SCENARIO, prior_lines=_laptop_prior(), search_fn=_good_search)
    plan = out["plan"]
    # prior laptop kept, quantity AMENDED 20 → 15, still $1800 context (no scoped budget on it)
    lap = next(l for l in plan if l.get("ref") == "LAP-1")
    assert lap["requested_qty"] == 15 and lap["scope"] == "prior" and lap.get("budget_max") is None
    # NEW lines fanned out with the SCOPED $1200, results within budget
    cats = {l["category"] for l in plan if l["scope"] == "new"}
    assert "headsets" in cats and any("drive" in c for c in cats)
    assert all(l["budget_max"] == 1200 for l in plan if l["scope"] == "new")
    # verified clean, but a mixed money-changing turn → confirm; price objection → value angle
    assert out["verdict"]["ok"] is True
    assert out["needs_confirmation"] is True
    assert out["objection_angle"] == "value"


def test_guard_catches_bad_fanout():
    # a search that returns a LAPTOP for a headset line → category mismatch → not ok → confirm
    def _bad_search(category, budget_max):
        return [{"name": "Some Laptop", "price_cents": 90000}]
    out = plan_turn("what options for headsets and cables for 1200 for those",
                    prior_lines=_laptop_prior(), search_fn=_bad_search)
    assert out["verdict"]["ok"] is False
    assert any("category mismatch" in v for v in out["verdict"]["violations"])
    assert out["needs_confirmation"] is True


def test_context_survival_enforced():
    # the laptop prior MUST survive; the planner always carries it → guard passes on survival
    out = plan_turn("what headsets for 1200 for those", prior_lines=_laptop_prior(), search_fn=_good_search)
    assert any(l.get("ref") == "LAP-1" for l in out["plan"])
    assert not any("context lost" in v for v in out["verdict"]["violations"])


def test_no_prior_selection_amendment_becomes_a_note_not_a_wrong_qty():
    out = plan_turn("actually make it 15 instead", prior_lines=None, search_fn=_good_search)
    # no prior item → the amendment is a note, not a silent qty change; nothing to amend
    assert out["intents"]["amendments"] == []
    assert any("no prior selection" in n for n in out["intents"]["notes"])
