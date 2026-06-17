"""Compound query decomposition — sub-question segmentation + intent per clause."""
from __future__ import annotations

from src.app.services.query_decomposer import decompose


def _texts(plan):
    return [sq.text.lower() for sq in plan.sub_questions]


def _intents(plan):
    return [sq.intent for sq in plan.sub_questions]


# ── Compound: should split ────────────────────────────────────────────────────

def test_uni_work_plus_budget_question_splits():
    p = decompose("what is good for uni work? is 1400 enough?")
    assert p.is_compound
    assert len(p.sub_questions) == 2
    assert any("uni work" in t for t in _texts(p))
    assert any("1400" in t for t in _texts(p))
    # the budget clause is flagged as a budget question
    assert any(sq.is_budget_question for sq in p.sub_questions)


def test_knowledge_plus_product_splits():
    p = decompose("what's the difference between SSD and HDD, and which laptop under 1200 has a good one?")
    assert p.is_compound
    # one conceptual (knowledge/comparison) + one product clause
    intents = set(_intents(p))
    assert intents & {"knowledge", "comparison"}
    assert "product_search" in intents or "recommendation_multi" in intents


def test_and_budget_question_conjunction_splits():
    p = decompose("show me lenovo laptops and is 1500 enough for video editing")
    assert p.is_compound
    assert any(sq.is_budget_question for sq in p.sub_questions)


# ── NOT compound: should stay whole ───────────────────────────────────────────

def test_single_product_request_not_compound():
    p = decompose("good laptop for university under 1500")
    assert not p.is_compound
    assert p.sub_questions == []


def test_use_case_list_not_fragmented():
    # "gaming and video editing" is a multi-use-case product request, NOT two questions.
    p = decompose("laptop for gaming and video editing that's portable")
    assert not p.is_compound
    assert "gaming" in p.use_cases and "video_editing" in p.use_cases


def test_gaming_under_budget_not_split_on_constraint():
    # "...and under 1500" is a constraint, not an independent budget *question*.
    p = decompose("laptop for gaming and under 1500")
    assert not p.is_compound


def test_empty_and_blank_safe():
    assert decompose("").sub_questions == []
    assert decompose(None).is_compound is False


# ── Backward compatibility of top-level fields ────────────────────────────────

def test_top_level_fields_preserved():
    p = decompose("RTX 4060 vs 4070")
    assert p.intent == "comparison"
    assert p.answer_without_products is True
    p2 = decompose("best laptop for gaming")
    assert p2.intent in ("product_search", "recommendation_multi")
