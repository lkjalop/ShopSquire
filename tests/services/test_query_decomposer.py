from src.app.services.query_decomposer import (
    decompose,
    INTENT_COMPARISON,
    INTENT_KNOWLEDGE,
    INTENT_MULTI,
    INTENT_PRODUCT_SEARCH,
    INTENT_SUPPORT,
)


def test_comparison_intent_extracts_subjects():
    p = decompose("what is the difference between the RTX 4060 and RTX 4070 gaming laptops?")
    assert p.intent == INTENT_COMPARISON
    assert p.answer_without_products is True
    assert len(p.comparison_subjects) == 2


def test_knowledge_intent():
    p = decompose("do i need 32gb ram for gaming?")
    assert p.intent == INTENT_KNOWLEDGE
    assert p.answer_without_products is True
    assert p.hard_constraints.get("ram_gb_min") == 32


def test_multi_intent_keeps_all_use_cases_and_portable():
    p = decompose("i need a laptop for gaming and video editing, portable, under 2000")
    assert p.intent == INTENT_MULTI
    assert p.is_multi_intent is True
    assert "gaming" in p.use_cases and "video_editing" in p.use_cases
    assert p.needs_dedicated_gpu is True
    assert p.hard_constraints.get("weight_kg_max") == 2.0
    assert p.hard_constraints.get("must_have_dedicated_gpu") is True


def test_numeric_refresh_constraint_extracted():
    p = decompose("best for competitive esports valorant at 240fps under 1900?")
    assert p.hard_constraints.get("refresh_hz_min") == 240
    assert p.answer_without_products is False  # it's a product search, not a concept


def test_plain_product_search_not_answer_without_products():
    p = decompose("what's good for gaming 1500-1900 why?")
    assert p.intent == INTENT_PRODUCT_SEARCH
    assert p.answer_without_products is False
    assert p.needs_dedicated_gpu is True


def test_support_intent():
    p = decompose("my laptop screen is cracked, can i return it?")
    assert p.intent == INTENT_SUPPORT


def test_empty_query_is_safe():
    p = decompose("")
    assert p.intent == INTENT_PRODUCT_SEARCH
    assert p.hard_constraints == {}
