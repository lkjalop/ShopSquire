"""Step 4 sub-answers: a compound query with a knowledge clause ("do I need an external hard
drive?") is identified as a conceptual sub-question and composed BEFORE the product section. The
composition pipeline is built + wired (gated by COMMERCE_COMPOSER); this verifies its contract
deterministically (the answer text itself comes from _build_knowledge_answer at runtime)."""
from __future__ import annotations

from src.app.services.answer_composer import (
    needs_composition, conceptual_sub_questions, compose_answer, AnswerSection,
)
from src.app.services.query_decomposer import decompose


def test_compound_with_hdd_question_needs_composition_and_extracts_it():
    plan = decompose(
        "budget is 1400 to 1700, what to get for corporate work or gaming? do i need an external hard drive?"
    )
    assert needs_composition(plan) is True
    concepts = conceptual_sub_questions(plan)
    assert any("hard drive" in c.lower() for c in concepts), f"HDD sub-question not extracted: {concepts}"


def test_compose_orders_knowledge_before_product():
    out = compose_answer([
        AnswerSection("product", "Here are 3 laptops."),
        AnswerSection("knowledge", "On the external drive: the bundled 1TB SSD is plenty for most."),
    ])
    assert "external drive" in out and "Here are 3 laptops." in out
    assert out.index("external drive") < out.index("Here are 3 laptops.")  # knowledge precedes product


def test_pure_product_query_needs_no_composition():
    assert needs_composition(decompose("gaming laptop under $1500")) is False
