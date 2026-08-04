"""Live-found bug (2026-06-24): NLP budget parser read spec units as budgets.

"a portable laptop under 2 kg" was parsed as budget_max=2 ($2), zeroing the catalog before the
weight filter could run (so the constraint-honesty path never fired and the page went blank). The
under/over/around budget regexes now reject a number followed by a spec/measurement unit, and a sane
floor drops nonsensical sub-$50 "budgets".
"""
from __future__ import annotations

import pytest

from src.app.services.nlp_search_agent import parse_query


@pytest.mark.parametrize("q", [
    "a portable gaming laptop for university under 2 kg",
    "under 2.5 kg", "16 gb ram under 2 kg", "laptop under 17 inch", "below 240 hz",
    "max 8 cores",
])
def test_spec_units_are_not_budgets(q):
    p = parse_query(q)
    assert p.budget_max is None, f"{q!r} -> spurious budget {p.budget_max}"


@pytest.mark.parametrize("q,expected_max", [
    ("laptop under 1500", 1500),
    ("laptop under 800 dollars", 800),
    ("under $1200", 1200),
    ("below 2000", 2000),
])
def test_real_budgets_still_parse(q, expected_max):
    assert parse_query(q).budget_max == expected_max


def test_sub_floor_budget_rejected():
    # "under 5" with no unit is still nonsensical as a product budget.
    assert parse_query("under 5").budget_max is None
