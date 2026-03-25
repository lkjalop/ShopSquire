"""Tests for orchestrator autonomy_tier / confidence gate logic.

These tests exercise the tier-assignment logic in isolation (pure dict manipulation)
without instantiating the full Orchestrator, which requires heavy service deps.
"""
from __future__ import annotations


def _apply_tier(intent_conf: float, fraud_score: float, approval_required: bool) -> dict:
    """Mirror of the confidence gate block added to orchestrator.run_nlp_cv()."""
    proposal: dict = {}
    policy: dict = {"approval_required": approval_required}

    if fraud_score >= 80:
        proposal["autonomy_tier"] = "denied"
        proposal["autonomy_badge"] = "DENIED — FRAUD SIGNAL"
    elif policy.get("approval_required"):
        proposal["autonomy_tier"] = "escalated"
        proposal["autonomy_badge"] = "ESCALATED"
    elif intent_conf < 0.60:
        proposal["autonomy_tier"] = "hold"
        proposal["autonomy_badge"] = "HOLD — LOW CONFIDENCE"
        proposal["confidence_gate_active"] = True
        proposal["confidence_gate_prefix"] = "I need to verify this before confirming — "
    elif intent_conf < 0.85:
        proposal["autonomy_tier"] = "caution"
        proposal["autonomy_badge"] = "CAUTION"
    else:
        proposal["autonomy_tier"] = "auto"
        proposal["autonomy_badge"] = "AUTO-RESOLVED"
    proposal["intent_confidence"] = round(intent_conf, 3)
    return proposal


def test_autonomy_tier_auto_on_high_confidence():
    p = _apply_tier(0.92, 0.0, False)
    assert p["autonomy_tier"] == "auto"
    assert p["autonomy_badge"] == "AUTO-RESOLVED"
    assert p["intent_confidence"] == 0.92


def test_autonomy_tier_hold_on_low_confidence():
    p = _apply_tier(0.45, 0.0, False)
    assert p["autonomy_tier"] == "hold"
    assert p.get("confidence_gate_active") is True
    assert "verify" in p.get("confidence_gate_prefix", "")


def test_autonomy_tier_denied_on_high_fraud():
    p = _apply_tier(0.95, 85.0, False)
    assert p["autonomy_tier"] == "denied"
    assert "FRAUD" in p["autonomy_badge"]


def test_autonomy_tier_escalated_on_approval_required():
    p = _apply_tier(0.95, 0.0, True)
    assert p["autonomy_tier"] == "escalated"
    assert p["autonomy_badge"] == "ESCALATED"


def test_autonomy_tier_caution_on_medium_confidence():
    p = _apply_tier(0.72, 0.0, False)
    assert p["autonomy_tier"] == "caution"


def test_fraud_takes_priority_over_escalation():
    """Fraud denial takes priority even when approval_required=True."""
    p = _apply_tier(0.99, 95.0, True)
    assert p["autonomy_tier"] == "denied"


def test_boundary_confidence_exactly_060():
    """Exactly 0.60 should be 'caution', not 'hold'."""
    p = _apply_tier(0.60, 0.0, False)
    assert p["autonomy_tier"] == "caution"


def test_boundary_confidence_exactly_085():
    """Exactly 0.85 should be 'auto'."""
    p = _apply_tier(0.85, 0.0, False)
    assert p["autonomy_tier"] == "auto"
