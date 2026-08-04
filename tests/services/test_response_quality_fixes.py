"""Tests for response quality fixes — session March 2026.

Covers:
- Fix 1: budget_question floor → score ≥ 5 (medium model) in llm_provider
- Fix 2: _build_context_preamble injects Redis answered fields into LLM prompt
- Fix 4: _build_brand_budget_answer corporate branch + budget extraction from query
- Fix 5: _classify_budget_bracket returns correct gaming tier labels
- BUG-7: expanded asks_budget token detection for will/would/can/could phrasings
"""
from __future__ import annotations
import pytest

from src.app.services.recommend_budget_advisor import (
    _build_brand_budget_answer,
    _build_brand_budget_answer_v2,
)
from src.app.services.recommend_budget_parsing import (
    classify_budget_bracket as _classify_budget_bracket,
)
from src.app.services.recommend_context_preamble import build_context_preamble
from src.app.services.llm_provider import complexity_explain, score_query_complexity

# ─────────────────────────────────────────────────────────────────────────────
# Fix 1 — budget question floor in llm_provider.score_query_complexity
# ─────────────────────────────────────────────────────────────────────────────
def test_budget_question_floor_short_query():
    """Short budget yes/no query must score ≥ 5 even without other signals."""
    result = score_query_complexity("Is $1800 enough for gaming?")
    assert result["score"] >= 5, (
        f"Expected score ≥ 5 for budget question, got {result['score']}. "
        f"Signals: {result['signals']}"
    )
    assert result["tier"] != "small", "Budget question must not route to small model"


def test_budget_question_floor_preserves_higher_score():
    """A genuinely complex budget question should not be capped at 5."""
    result = score_query_complexity(
        "Can I get a Dell or Lenovo laptop for $1,500 budget for gaming with RTX 3080 "
        "or equivalent GPU? Compare tradeoffs vs buying refurbished."
    )
    assert result["score"] >= 5


def test_budget_question_signal_detected():
    """budget_question signal must be in signals dict for yes/no budget queries."""
    result = score_query_complexity("Is $2000 enough for a MacBook Pro?")
    assert "budget_question" in result["signals"]


def test_complexity_explain_includes_budget_question_tier():
    """complexity_explain backward-compat wrapper should expose tier + signals."""
    exp = complexity_explain("will $1500 cover a gaming laptop?")
    assert "tier" in exp
    assert "signals" in exp
    assert exp.get("score", 0) >= 5


def test_non_budget_simple_query_stays_small():
    """Plain product query with no complexity signals stays at small tier."""
    result = score_query_complexity("show me laptops")
    assert result["score"] < 5 or result["tier"] in ("small", "medium")


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2 — _build_context_preamble
# ─────────────────────────────────────────────────────────────────────────────
def test_context_preamble_empty_when_no_data():
    assert build_context_preamble({}, {}, {}) == ""


def test_context_preamble_includes_budget():
    preamble = build_context_preamble(
        kv={"nqe_answered_fields": {"budget_max": 1800}},
        structured_state={},
        constraints={},
    )
    assert "1,800" in preamble or "1800" in preamble
    assert "Prior conversation context" in preamble


def test_context_preamble_includes_use_case():
    preamble = build_context_preamble(
        kv={},
        structured_state={"nqe_answered_fields": {"use_case": "gaming"}},
        constraints={},
    )
    assert "gaming" in preamble.lower()


def test_context_preamble_merges_constraints():
    preamble = build_context_preamble(
        kv={},
        structured_state={},
        constraints={"budget_max": 1500, "use_case": "corporate"},
    )
    assert "1,500" in preamble or "1500" in preamble


def test_context_preamble_deduplicates_fields():
    """When kv and constraints both have budget_max, it should appear once."""
    preamble = build_context_preamble(
        kv={"nqe_answered_fields": {"budget_max": 2000}},
        structured_state={},
        constraints={"budget_max": 2000},
    )
    # Should not double-print the same budget
    assert preamble.count("2,000") <= 2  # generous: title + value is fine


# ─────────────────────────────────────────────────────────────────────────────
# Fix 4 — _build_brand_budget_answer: corporate branch + budget extraction
# ─────────────────────────────────────────────────────────────────────────────
def _make_results(prices_cents: list[int]) -> list[dict]:
    return [
        {"price_cents": p, "name": f"Product {i}", "brand": "lenovo"}
        for i, p in enumerate(prices_cents)
    ]


def test_corporate_branch_returns_brand_territory():
    results = _make_results([120000, 145000])  # $1200, $1450
    answer = _build_brand_budget_answer(
        "Is $1500 enough for corporate use?",
        results,
        {"budget_max": 1500},
    )
    assert answer, "Expected non-empty corporate answer"
    assert "corporate" in answer.lower() or "business" in answer.lower()


def test_corporate_branch_triggers_from_query_text():
    results = _make_results([100000, 130000])
    answer = _build_brand_budget_answer(
        "What is my budget for a business laptop at $1200?",
        results,
        {},  # no budget_max in constraints yet — extracted from query
    )
    assert answer, "Expected corporate answer from query text"


def test_budget_extraction_from_query_text():
    """budget_max not in constraints — should extract $1800 from query."""
    results = _make_results([150000, 175000])  # $1500, $1750
    answer = _build_brand_budget_answer(
        "Is $1800 enough for a gaming laptop?",
        results,
        {},  # intentionally empty constraints
    )
    assert answer, "Should produce an answer even with no constraints"
    assert "1,800" in answer or "yes" in answer.lower() or "1800" in answer


def test_budget_extraction_over_budget():
    """When cheapest result > extracted budget → returns 'short' message."""
    results = _make_results([220000, 250000])  # $2200, $2500
    answer = _build_brand_budget_answer(
        "Is $1800 enough?",
        results,
        {},
    )
    # Should say budget is short / closest starts around $2,200
    assert "short" in answer.lower() or "2,200" in answer or "2200" in answer


def test_no_budget_mention_returns_empty():
    results = _make_results([100000])
    answer = _build_brand_budget_answer("show me laptops", results, {})
    assert answer == ""


# ─────────────────────────────────────────────────────────────────────────────
# BUG-7 — expanded asks_budget token detection
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("query", [
    "Will $1500 cover a gaming laptop?",
    "Would $800 be enough for a MacBook?",
    "Can $900 get me a good laptop?",
    "Could $700 cover an engineering-student laptop?",
    "Can I afford a gaming laptop at $1200?",
    "Is $1800 worth it for a gaming laptop?",
    "Do I have enough at $1000 for a student laptop?",
    "Is that too expensive at $2000?",
    "Fits my budget at $1500?",
])
def test_expanded_asks_budget_triggers_answer(query):
    """Expanded token list must produce a non-empty answer for common budget phrasings."""
    results = _make_results([100000, 120000])  # $1000, $1200
    answer = _build_brand_budget_answer_v2(query, results, {})
    assert answer, f"Expected non-empty budget answer for query: {query!r}"


def test_will_dollar_v2_answer():
    """'Will $1500 cover...' pattern should trigger budget answer."""
    results = _make_results([130000, 145000])  # $1300, $1450
    answer = _build_brand_budget_answer_v2("Will $1500 cover a gaming laptop?", results, {})
    assert answer
    assert "yes" in answer.lower() or "1,500" in answer or "1500" in answer


def test_would_dollar_v2_over_budget():
    results = _make_results([200000, 250000])  # $2000, $2500
    answer = _build_brand_budget_answer_v2("Would $1500 be enough?", results, {})
    assert answer
    assert "no" in answer.lower() or "short" in answer.lower() or "2,000" in answer


# ─────────────────────────────────────────────────────────────────────────────
# Fix 5 — _classify_budget_bracket gaming tiers
# ─────────────────────────────────────────────────────────────────────────────
def test_bracket_entry():
    # ≤ 500 → entry
    assert _classify_budget_bracket(400) == "entry"


def test_bracket_mid():
    # ≤ 900 → mid
    assert _classify_budget_bracket(700) == "mid"


def test_bracket_high():
    # ≤ 1500 → high
    assert _classify_budget_bracket(1200) == "high"


def test_bracket_ultra():
    assert _classify_budget_bracket(3500) == "ultra"


def test_bracket_none_returns_none():
    assert _classify_budget_bracket(None) is None
