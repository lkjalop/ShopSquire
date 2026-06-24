"""Unit tests for src.app.services.recommend_message_decorator."""
from __future__ import annotations

import pytest

from src.app.services.recommend_message_decorator import (
    apply_budget_advice,
    apply_contextual_notes,
    apply_constraint_honesty_prefix,
    build_comparative_synthesis,
    apply_price_range_note,
    apply_confidence_gate,
    apply_security_event_prefix,
)


# ──────────────────────────────────────────────────────────────────────
# apply_budget_advice
# ──────────────────────────────────────────────────────────────────────
class TestApplyBudgetAdvice:
    def test_low_budget_appends_advice_and_alternatives(self):
        constraints = {"budget_fitness": {"status": "low", "advice": "Consider refurbished.", "floor": 1200}}
        msg, payload = apply_budget_advice("Original.", constraints, {})
        assert "Consider refurbished." in msg
        assert "alternatives" in payload
        assert any("$1,200" in a for a in payload["alternatives"])

    def test_high_budget_appends_advice(self):
        constraints = {"budget_fitness": {"status": "high", "advice": "You can upgrade."}}
        msg, payload = apply_budget_advice("Hello", constraints, {})
        assert "You can upgrade." in msg

    def test_no_budget_info_noop(self):
        msg, payload = apply_budget_advice("Hello", {}, {"foo": 1})
        assert msg == "Hello"
        assert payload == {"foo": 1}

    def test_none_message_gets_advice_only(self):
        constraints = {"budget_fitness": {"status": "low", "advice": "Raise it.", "floor": 500}}
        msg, _ = apply_budget_advice(None, constraints, {})
        assert msg == "Raise it."


# ──────────────────────────────────────────────────────────────────────
# apply_contextual_notes
# ──────────────────────────────────────────────────────────────────────
class TestApplyContextualNotes:
    def test_appends_all_notes(self):
        msg = apply_contextual_notes(
            "Base",
            image_brand_mismatch_note="Mismatch!",
            brand_budget_answer=None,
            gpu_inference_note="GPU note.",
            availability_line="In stock.",
        )
        assert "Mismatch!" in msg
        assert "GPU note." in msg
        assert "In stock." in msg

    def test_skips_brand_note_when_budget_answer_present(self):
        msg = apply_contextual_notes(
            "Base",
            image_brand_mismatch_note="Mismatch!",
            brand_budget_answer={"answer": True},
            gpu_inference_note=None,
            availability_line=None,
        )
        assert "Mismatch!" not in msg

    def test_none_message_becomes_note(self):
        msg = apply_contextual_notes(
            None,
            image_brand_mismatch_note=None,
            brand_budget_answer=None,
            gpu_inference_note="GPU.",
            availability_line=None,
        )
        assert msg == "GPU."


# ──────────────────────────────────────────────────────────────────────
# apply_constraint_honesty_prefix
# ──────────────────────────────────────────────────────────────────────
class TestConstraintHonestyPrefix:
    def test_prepends_relaxation_note(self):
        constraints = {"constraint_status": {"exact_match": False, "relaxation_note": "No exact match."}}
        msg = apply_constraint_honesty_prefix("Here are options.", constraints)
        assert msg.startswith("No exact match.")

    def test_exact_match_noop(self):
        constraints = {"constraint_status": {"exact_match": True, "relaxation_note": "Should not appear."}}
        msg = apply_constraint_honesty_prefix("Hello", constraints)
        assert msg == "Hello"


# ──────────────────────────────────────────────────────────────────────
# build_comparative_synthesis
# ──────────────────────────────────────────────────────────────────────
class TestBuildComparativeSynthesis:
    def _humanize(self, items):
        return [str(x) for x in (items or [])]

    def test_returns_synthesis_for_comparison_query(self):
        results = [
            {"name": "Laptop A", "price_cents": 100000, "factors": {"positive": ["+in_stock"]}},
            {"name": "Laptop B", "price_cents": 120000, "factors": {"positive": []}},
        ]
        out = build_comparative_synthesis("which is better for coding?", results, self._humanize)
        assert out is not None
        assert "Laptop A" in out
        assert "Laptop B" in out

    def test_returns_none_for_non_comparison_query(self):
        results = [{"name": "X", "price_cents": 50000, "factors": {}}]
        out = build_comparative_synthesis("show me laptops", results, self._humanize)
        assert out is None

    def test_returns_none_when_no_results(self):
        out = build_comparative_synthesis("which is better?", [], self._humanize)
        assert out is None


# ──────────────────────────────────────────────────────────────────────
# apply_price_range_note
# ──────────────────────────────────────────────────────────────────────
class TestApplyPriceRangeNote:
    def test_appends_price_range_note(self):
        payload = {"price_range": {"min": 500, "max": 1500, "median": 900, "count": 5}}
        msg = apply_price_range_note("Picks:", payload)
        assert "$500" in msg
        assert "$1,500" in msg
        assert "median" in msg

    def test_no_price_range_noop(self):
        msg = apply_price_range_note("Hello", {})
        assert msg == "Hello"

    def test_single_result_no_note(self):
        payload = {"price_range": {"min": 500, "max": 500, "median": 500, "count": 1}}
        msg = apply_price_range_note("Hello", payload)
        assert msg == "Hello"


# ──────────────────────────────────────────────────────────────────────
# apply_confidence_gate
# ──────────────────────────────────────────────────────────────────────
class TestApplyConfidenceGate:
    def test_fraud_denied(self):
        msg, p = apply_confidence_gate("Hello", {}, intent_confidence=0.9, fraud_score=85.0, policy_approval_required=False)
        assert p["autonomy_tier"] == "denied"
        assert msg == "Hello"  # no prefix

    def test_escalated(self):
        msg, p = apply_confidence_gate("Hello", {}, intent_confidence=0.9, fraud_score=10.0, policy_approval_required=True)
        assert p["autonomy_tier"] == "escalated"

    def test_hold_low_confidence(self):
        msg, p = apply_confidence_gate("Hello", {}, intent_confidence=0.4, fraud_score=0.0, policy_approval_required=False)
        assert p["autonomy_tier"] == "hold"
        assert msg.startswith("I need to verify")
        assert p["confidence_gate_active"] is True

    def test_caution(self):
        msg, p = apply_confidence_gate("Hello", {}, intent_confidence=0.7, fraud_score=0.0, policy_approval_required=False)
        assert p["autonomy_tier"] == "caution"
        assert msg == "Hello"

    def test_auto_resolved(self):
        msg, p = apply_confidence_gate("Hello", {}, intent_confidence=0.95, fraud_score=0.0, policy_approval_required=False)
        assert p["autonomy_tier"] == "auto"
        assert p["intent_confidence"] == 0.95


# ──────────────────────────────────────────────────────────────────────
# apply_security_event_prefix
# ──────────────────────────────────────────────────────────────────────
class TestApplySecurityEventPrefix:
    def test_steg_flag(self):
        signals = {"steg_suspicious": True}
        msg = apply_security_event_prefix("Hello", image_cv_signals_parsed=signals, has_incoming_image=True)
        assert "[SECURITY]" in msg
        assert "steganography" in msg

    def test_no_image_no_prefix(self):
        signals = {"steg_suspicious": True}
        msg = apply_security_event_prefix("Hello", image_cv_signals_parsed=signals, has_incoming_image=False)
        assert msg == "Hello"

    def test_multiple_flags(self):
        signals = {"steg_suspicious": True, "qr_prompt_injection": True, "adversarial_score": 0.5}
        msg = apply_security_event_prefix("Test", image_cv_signals_parsed=signals, has_incoming_image=True)
        assert "steganography" in msg
        assert "QR prompt injection" in msg
        assert "adversarial" in msg

    def test_none_message_gets_fallback(self):
        signals = {"manipulation_detected": True}
        msg = apply_security_event_prefix(None, image_cv_signals_parsed=signals, has_incoming_image=True)
        assert "text query only" in msg
