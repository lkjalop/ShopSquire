"""Roadmap #2 — unify query understanding: comma budgets + office-staff classification.

Comma-formatted budgets ("$1,600") must parse consistently, and "office staff" must classify as an
office use-case (not nothing, and not the audit's reported high_school). Profile-driven (electronics
adapter); the decomposer mechanism stays agnostic.
"""
from __future__ import annotations

import pytest

from src.app.services.query_decomposer import _extract_budget_range, decompose


@pytest.mark.parametrize("q,expected", [
    ("gaming laptop budget is $1,600", (None, 1600)),
    ("laptop under $1,500", (None, 1500)),
    ("between $1,300 and $1,500", (1300, 1500)),
    ("$12,000 budget for the fleet", (None, 12000)),
    ("laptop under 1500", (None, 1500)),          # plain still works
    ("between 1300 and 1700", (1300, 1700)),
])
def test_comma_and_plain_budgets_parse(q, expected):
    assert _extract_budget_range(q) == expected


@pytest.mark.parametrize("q", [
    "laptops for office staff", "laptops for our staff", "10 staff laptops for the company",
])
def test_office_staff_classifies_as_office_not_highschool(q):
    ucs = decompose(q).use_cases
    assert "office" in ucs
    assert "high_school" not in ucs and "study" not in ucs


def test_office_staff_budget_together():
    p = decompose("10 laptops for office staff, budget is $1,600")
    assert "office" in p.use_cases
    assert p.budget_max == 1600
    assert p.quantity == 10
