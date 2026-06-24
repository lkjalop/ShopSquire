"""Live Tier-0 finding: RecommendationService.parse_constraints read spec units as budgets.

"a laptop under 2 kg" → budget_max=2 (and "under 2kg" → $2000) zeroed the catalog before the weight
filter, blanking the page. parse_constraints now rejects unit-qualified numbers and sub-$50 budgets.
"""
from __future__ import annotations

import pytest

from src.app.services.recommendations import RecommendationService


def _svc():
    return RecommendationService.__new__(RecommendationService)


@pytest.mark.parametrize("q", [
    "a laptop under 2 kg", "under 2kg laptop", "under 2.5 kg", "16 gb under 2 kg",
    "under 17 inch", "below 240 hz",
])
def test_units_not_budget(q):
    assert "budget_max" not in _svc().parse_constraints(q)


@pytest.mark.parametrize("q,expected", [
    ("laptop under 1500", 1500),
    ("under $1500", 1500),
    ("under 2k", 2000),
])
def test_real_budgets_parse(q, expected):
    assert _svc().parse_constraints(q).get("budget_max") == expected


def test_range_still_parses():
    out = _svc().parse_constraints("between 1300 and 1500")
    assert out.get("budget_min") == 1300 and out.get("budget_max") == 1500
