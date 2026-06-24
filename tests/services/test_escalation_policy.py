"""Escalation policy — deterministic risk/complexity → human-in-the-loop decision.

Locks: clean low-risk requests auto-proceed; fraud, irreversible-bulk, B2B+fraud, and
constraint-conflict-on-value force a human; the function never raises and fails SAFE.
"""
from __future__ import annotations

from src.app.services.escalation_policy import (
    BAND_AUTO, BAND_HUMAN, BAND_REVIEW, assess_escalation,
)


def test_clean_simple_request_auto_proceeds():
    d = assess_escalation(decomposition_confidence=0.9, irreversible_action=False,
                          order_quantity=1, fraud_score=0.0)
    assert d.band == BAND_AUTO and d.escalate is False


def test_high_fraud_forces_human():
    d = assess_escalation(fraud_score=0.85)
    assert d.band == BAND_HUMAN and d.escalate is True
    assert any("fraud" in r for r in d.reasons)


def test_irreversible_bulk_forces_human():
    # 50 units to be carted/purchased → irreversible + bulk → human required.
    d = assess_escalation(irreversible_action=True, order_quantity=50, order_value_cents=8_000_00)
    assert d.band == BAND_HUMAN and d.escalate is True


def test_b2b_with_elevated_fraud_forces_human():
    d = assess_escalation(b2b=True, order_quantity=20, fraud_score=0.4, irreversible_action=False)
    assert d.band == BAND_HUMAN and d.escalate is True


def test_constraint_conflict_on_high_value_escalates():
    d = assess_escalation(constraint_conflict=True, order_value_cents=9_000_00, order_quantity=6)
    assert d.escalate is True


def test_low_confidence_irreversible_escalates_softly():
    d = assess_escalation(decomposition_confidence=0.2, irreversible_action=True,
                          order_quantity=1, fraud_score=0.0)
    assert d.escalate is True
    assert any("confidence" in r for r in d.reasons)


def test_claim_guard_rejection_contributes():
    d = assess_escalation(claim_guard_rejected=True, decomposition_confidence=0.3,
                          constraint_conflict=True)
    assert d.escalate is True
    assert any("ungrounded" in r or "narration" in r for r in d.reasons)


def test_score_is_bounded_and_factors_present():
    d = assess_escalation(decomposition_confidence=0.0, fraud_score=1.0, constraint_conflict=True,
                          claim_guard_rejected=True, irreversible_action=True, order_quantity=100)
    assert 0.0 <= d.score <= 1.0
    assert set(d.factors) >= {"fraud", "uncertainty", "constraint_conflict"}


def test_to_dict_roundtrips():
    d = assess_escalation(fraud_score=0.9)
    payload = d.to_dict()
    assert payload["escalate"] is True and payload["band"] == BAND_HUMAN
    assert isinstance(payload["reasons"], list) and isinstance(payload["factors"], dict)
