"""Decomposition permutation/property tests (GPT-5.5 live-track findings, 2026-06-24).

Live testing surfaced parser permutations that broke: spec units read as quantities ("144 fps" → 10),
number words unparsed ("ten laptops", "in fourteen days"), negated-statement false exclusions
("not set a budget"), and rationale follow-ups mis-routed ("why those?"). These lock the fixes and
guard against regression across equivalent phrasings.
"""
from __future__ import annotations

import pytest

from src.app.services.query_decomposer import (
    _extract_availability_horizon,
    _extract_exclusions,
    _extract_quantity,
    decompose,
)


# ── spec units must NEVER be read as a bulk quantity ─────────────────────────
@pytest.mark.parametrize("q", [
    "show me a 144 fps gaming laptop", "a 240 hz laptop", "16 gb ram", "512 gb ssd",
    "2 tb storage", "a 17 inch screen", "2.9 kg ultrabook", "100 nits brighter", "8 cores",
])
def test_spec_values_are_not_quantities(q):
    assert _extract_quantity(q) is None, q


# ── number words parse like their digit forms ────────────────────────────────
@pytest.mark.parametrize("q,expected", [
    ("ten work laptops", 10), ("a dozen monitors", 12), ("fifteen units", 15),
    ("twenty laptops for the office", 20), ("10 laptops", 10),
])
def test_number_word_quantities(q, expected):
    assert _extract_quantity(q) == expected


# ── "<N> in/within <M> days" — N is the bulk quantity, the horizon is not (the screenshot bug) ──
@pytest.mark.parametrize("q,expected", [
    ("what about laptops for work around 1800 to 2100? i need about 30 in 10 days?", 30),
    ("30 in 10 days", 30),
    ("i need 50 within 2 weeks", 50),
    ("i need it within 10 days", None),   # no leading count → not a quantity
    ("delivery in 4 weeks", None),        # horizon only
])
def test_quantity_from_delivery_horizon(q, expected):
    assert _extract_quantity(q) == expected


@pytest.mark.parametrize("q,expected_days", [
    ("deliver in fourteen days", 14), ("in two weeks", 14), ("within three days", 3),
    ("in 4 weeks", 28), ("by ten days", 10),
])
def test_number_word_horizons(q, expected_days):
    assert _extract_availability_horizon(q) == expected_days


# ── negated statements about budget/decisions are NOT product exclusions ──────
@pytest.mark.parametrize("q", [
    "I have not set a budget yet", "I haven't got a budget", "no budget in mind",
    "I haven't decided on a brand", "not sure what I need", "no rush",
])
def test_negated_statements_do_not_create_exclusions(q):
    assert _extract_exclusions(q, "laptop") == [], q


def test_real_brand_exclusion_still_works():
    assert "apple" in _extract_exclusions("a laptop but not Apple", "laptop")


# ── rationale follow-ups are explanation intent, not a fresh product search ───
@pytest.mark.parametrize("q", [
    "why those?", "why these ones?", "why did you pick the first one?", "why that one?",
])
def test_why_those_is_explanation(q):
    p = decompose(q)
    assert p.intent == "knowledge" and p.answer_without_products is True, q


# ── property: equivalent digit/word phrasings decompose the same ──────────────
def test_digit_and_word_quantity_equivalent():
    assert decompose("ten laptops under $1500").quantity == decompose("10 laptops under $1500").quantity
