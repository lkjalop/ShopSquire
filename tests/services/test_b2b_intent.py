"""B2B intent assessment — quantity is a signal, not a deterministic gate.

Per the design directive: figure out from the query whether the buyer actually wants a business/bulk
purchase (don't B2B-route on a raw count), flag ambiguity for human review, mark discount eligibility,
and treat absurd quantities as a possible prompt attack / too-large-to-auto-quote → escalate.
"""
from __future__ import annotations

from src.app.services.b2b_intent import (
    VERDICT_ANOMALOUS, VERDICT_AMBIGUOUS_BULK, VERDICT_B2B, VERDICT_CONSUMER, assess_b2b_intent,
)


def test_business_language_is_b2b_even_at_low_qty():
    a = assess_b2b_intent("2 laptops for the office", quantity=2)
    assert a.verdict == VERDICT_B2B and a.is_b2b
    assert a.discount_eligible is False  # business but not bulk
    # A few business laptops is B2B, but NOT a fleet-procurement scenario — the corporate use-case
    # refinement handles it; the fleet pack is reserved for bulk orders.
    assert a.wants_procurement_questions is False


def test_business_bulk_is_discount_eligible():
    a = assess_b2b_intent("10 laptops for our company", quantity=10)
    assert a.verdict == VERDICT_B2B and a.discount_eligible is True
    assert a.escalate is False


def test_bulk_without_business_signal_is_ambiguous_and_escalates():
    # 10 units but no business language → don't assume B2B; clarify + flag for review.
    a = assess_b2b_intent("I want 10 laptops", quantity=10)
    assert a.verdict == VERDICT_AMBIGUOUS_BULK
    assert a.escalate is True and a.discount_eligible is False
    assert a.wants_procurement_questions is True  # the question disambiguates


def test_personal_cue_overrides_business_keyword():
    # "for my family" is personal even with a few units → consumer, no B2B questions.
    a = assess_b2b_intent("3 laptops for my family", quantity=3)
    assert a.verdict == VERDICT_CONSUMER
    assert a.wants_procurement_questions is False


def test_small_consumer_purchase():
    a = assess_b2b_intent("a gaming laptop", quantity=1)
    assert a.verdict == VERDICT_CONSUMER and a.escalate is False


def test_absurd_quantity_is_anomalous_and_escalates():
    a = assess_b2b_intent("buy 999999 laptops for the company", quantity=999999)
    assert a.verdict == VERDICT_ANOMALOUS
    assert a.escalate is True
    assert any("ceiling" in r or "human" in r for r in a.reasons)


def test_thresholds_are_overridable():
    # With bulk_min=3, three units becomes bulk.
    a = assess_b2b_intent("3 laptops", quantity=3, bulk_min=3)
    assert a.is_bulk is True and a.verdict == VERDICT_AMBIGUOUS_BULK


def test_never_raises_and_to_dict():
    a = assess_b2b_intent(None, quantity=None)
    assert a.verdict in (VERDICT_CONSUMER, VERDICT_AMBIGUOUS_BULK)
    d = a.to_dict()
    assert "verdict" in d and "discount_eligible" in d and "escalate" in d
