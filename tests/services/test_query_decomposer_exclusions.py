"""NEW-4 — negation/exclusion in decomposition (agnostic core).

The decomposer must surface what the shopper does NOT want ("but not Apple", "without a
touchscreen", "no refurbished") as `QueryPlan.exclusions`, using grammar only (no hardcoded
brand literals). It must be fail-safe: never strip the search category, and never fire on
comparatives/idioms ("no more than $1500", "not sure", "no rush").
"""
from __future__ import annotations

from src.app.services.query_decomposer import _extract_exclusions, decompose


# ── direct extractor ─────────────────────────────────────────────────────────
def test_but_not_brand():
    assert "apple" in _extract_exclusions("gaming laptop but not Apple", "laptop")


def test_without_feature():
    assert "touchscreen" in _extract_exclusions("a laptop without a touchscreen", "laptop")


def test_dont_want_brand():
    assert "lenovo" in _extract_exclusions("I don't want Lenovo", "laptop")
    assert "hp" in _extract_exclusions("anything but HP", "laptop")


def test_excluding_and_except():
    assert "refurbished" in _extract_exclusions("show laptops excluding refurbished", "laptop")
    assert "dell" in _extract_exclusions("any laptop except Dell", "laptop")


def test_sibling_alternatives_split_on_or_and():
    terms = _extract_exclusions("a laptop but not Apple or Dell", "laptop")
    assert "apple" in terms and "dell" in terms


# ── fail-safe guards (no false positives) ────────────────────────────────────
def test_comparative_budget_not_excluded():
    assert _extract_exclusions("a gaming laptop, no more than $1500", "laptop") == []
    assert _extract_exclusions("not more than 32gb of ram", "laptop") == []


def test_idioms_and_uncertainty_not_excluded():
    assert _extract_exclusions("not sure what I need", "laptop") == []
    assert _extract_exclusions("a laptop, no rush", "laptop") == []


def test_search_category_never_excluded():
    # "I don't want a laptop" while shopping laptops must not nuke the whole result set.
    assert "laptop" not in _extract_exclusions("I don't want a cheap laptop", "laptop")


def test_notebook_word_boundary_not_a_negation():
    # "notebook" contains "not" but is not a negation cue.
    assert _extract_exclusions("a notebook for work", "laptop") == []


def test_plain_query_has_no_exclusions():
    assert _extract_exclusions("gaming laptop under $1500", "laptop") == []


# ── end-to-end via decompose() — additive, never changes intent ──────────────
def test_decompose_surfaces_exclusions_without_changing_intent():
    plan = decompose("show me a gaming laptop but not Apple")
    assert "apple" in plan.exclusions
    assert plan.intent == "product_search"  # exclusions are additive, not an intent flip


def test_decompose_plain_query_empty_exclusions():
    plan = decompose("a good laptop for university under $1200")
    assert plan.exclusions == []
    assert "exclusions" in plan.to_dict()
