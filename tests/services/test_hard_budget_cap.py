"""PX2 (GPT-5.5 #2, 2026-07-10): hard budget cap — 'nothing over $2000' must not leak >cap.

The local override regex read 'nothing over' / 'not above' as a budget FLOOR (min), inverting
the cap, so over-budget products leaked. Fixed by delegating to budget_grammar (the one money
parser) + a hard_cap flag that disables the nearest-above fallback."""
from __future__ import annotations

from src.app.services.recommend_budget_parsing import extract_explicit_budget_override as _ov


def test_negated_over_phrases_are_ceilings_not_floors():
    for q, cap in [("nothing over $2000", 2000), ("not above 1800", 1800),
                   ("no more than 1500", 1500), ("laptops for a team but nothing over 2000", 2000)]:
        r = _ov(q)
        assert r.get("budget_max") == cap, f"{q}: got {r}"
        assert r.get("budget_min") is None, f"{q}: must be a ceiling, not a floor — {r}"
        assert r.get("hard_cap") is True, f"{q}: must mark hard_cap — {r}"


def test_real_floor_stays_a_floor():
    r = _ov("over 2000")
    assert r.get("budget_min") == 2000 and r.get("budget_max") is None


def test_legacy_gaps_still_covered():
    # bare range + "is N enough" are NOT handled by the grammar — legacy patterns must still fire
    assert _ov("1200 to 1500") == {"budget_min": 1200, "budget_max": 1500, "mode": "range"}
    assert _ov("is 3500 enough").get("budget_max") == 3500


def test_ranges_via_grammar():
    r = _ov("between 1200 and 1500")
    assert r.get("budget_min") == 1200 and r.get("budget_max") == 1500
