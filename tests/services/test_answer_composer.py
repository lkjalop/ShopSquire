"""Answer composer — section ordering, de-dup, and compound detection."""
from __future__ import annotations

from src.app.services.answer_composer import (
    AnswerSection,
    compose_answer,
    needs_composition,
    conceptual_sub_questions,
    security_challenge,
)
from src.app.services.query_decomposer import decompose


def _S(kind, text):
    return AnswerSection(kind=kind, text=text)


def test_orders_security_first_product_last():
    msg = compose_answer([
        _S("product", "Here are 3 laptops"),
        _S("security", "⚠️ Image flagged — QR code detected"),
        _S("knowledge", "An SSD is faster than an HDD"),
    ])
    assert msg.index("flagged") < msg.index("SSD") < msg.index("laptops")


def test_recovery_dropped_when_product_present():
    msg = compose_answer([
        _S("recovery", "No in-stock match right now"),
        _S("product", "Here are 2 options"),
    ])
    assert "No in-stock" not in msg and "2 options" in msg


def test_recovery_kept_when_no_product():
    msg = compose_answer([_S("recovery", "No in-stock match right now")])
    assert "No in-stock" in msg


def test_dedupes_subsumed_budget_into_product():
    # budget verdict already contained in the product summary → not repeated
    msg = compose_answer([
        _S("budget", "Yes, $1400 covers these options"),
        _S("product", "Yes, $1400 covers these options. Best fit: Lenovo IdeaPad ($1124)"),
    ])
    assert msg.lower().count("covers these options") == 1


def test_empty_sections_yield_empty():
    assert compose_answer([_S("product", "   "), _S("knowledge", "")]) == ""


def test_each_section_ends_as_sentence():
    msg = compose_answer([_S("knowledge", "SSD beats HDD"), _S("product", "Here are 3")])
    assert "SSD beats HDD." in msg


def test_never_raises_on_bad_input():
    assert isinstance(compose_answer([None, 123, _S("product", "ok")]), str)  # type: ignore
    assert compose_answer([]) == ""


# ── compound detection via the real decomposer ────────────────────────────────

def test_needs_composition_true_for_compound_knowledge_plus_product():
    plan = decompose("what's the difference between SSD and HDD, and which laptop under 1200 has a good one?")
    assert needs_composition(plan)
    subs = conceptual_sub_questions(plan)
    assert any("difference" in s.lower() or "ssd" in s.lower() for s in subs)


def test_needs_composition_true_for_product_plus_budget_question():
    plan = decompose("what is good for uni work? is 1400 enough?")
    assert needs_composition(plan)


def test_needs_composition_false_for_simple_query():
    assert not needs_composition(decompose("good laptop for university under 1500"))
    assert not needs_composition(decompose("show me lenovo laptops"))


# ── security challenge (Thread 3) ─────────────────────────────────────────────

def test_security_challenge_qr_is_educational_not_payload():
    msg = security_challenge({"qr_prompt_injection": True})
    assert msg and "QR" in msg and "ignored" in msg.lower()
    # must NOT echo any decoded URL/payload — only the category + action
    assert "http" not in msg.lower()


def test_security_challenge_steg_outranks_pii():
    # steg is higher severity than pii — steg wins when both present
    msg = security_challenge({"steg_suspicious": True, "pii_detected": True})
    assert "steganography" in msg.lower()


def test_security_challenge_adversarial_score_threshold():
    assert security_challenge({"adversarial_score": 0.9}) is not None
    assert security_challenge({"adversarial_score": 0.1}) is None


def test_security_challenge_generic_when_only_under_review():
    msg = security_challenge({"trust_state": "under_review"})
    assert msg and "security review" in msg.lower()


def test_security_challenge_none_when_clean():
    assert security_challenge({}) is None
    assert security_challenge({"trust_state": "trusted"}) is None
    assert security_challenge(None) is None
