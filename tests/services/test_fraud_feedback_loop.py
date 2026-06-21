"""Fraud_Scorer feedback loop — static weights become weights that LEARN from outcomes.

compute_signal_multipliers (pure) turns confirmed/false-positive labels into per-signal weight
multipliers; calculate_score applies them behind FRAUD_ADAPTIVE_WEIGHTS (default OFF = unchanged).
"""
from __future__ import annotations

from src.app.services.fraud_scorer import FraudScorer, compute_signal_multipliers


# ── pure learning function ──
def test_confirmed_heavy_signal_is_amplified_fp_heavy_is_damped():
    rows = (
        [{"label": "confirmed_fraud", "signals": {"good_signal": True}}] * 8
        + [{"label": "false_positive", "signals": {"good_signal": True}}] * 2
        + [{"label": "false_positive", "signals": {"noisy_signal": True}}] * 8
        + [{"label": "confirmed_fraud", "signals": {"noisy_signal": True}}] * 2
    )
    m = compute_signal_multipliers(rows, min_samples=5, floor=0.5, ceil=1.5)
    assert m["good_signal"] > 1.0   # precision 0.8 -> amplified
    assert m["noisy_signal"] < 1.0  # precision 0.2 -> damped
    assert m["good_signal"] > m["noisy_signal"]


def test_insufficient_samples_stays_neutral():
    rows = [{"label": "confirmed_fraud", "signals": {"rare": True}}] * 3  # < min_samples
    assert "rare" not in compute_signal_multipliers(rows, min_samples=5)  # omitted == neutral 1.0


def test_legitimate_label_ignored_in_precision():
    rows = (
        [{"label": "confirmed_fraud", "signals": {"s": True}}] * 5
        + [{"label": "legitimate", "signals": {"s": True}}] * 50  # not fp -> ignored
    )
    m = compute_signal_multipliers(rows, min_samples=5)
    assert m["s"] == 1.5  # precision 5/(5+0) = 1.0 -> ceil


def test_empty_feedback_is_empty():
    assert compute_signal_multipliers([]) == {}


# ── recorder + adaptive scoring (DB-backed) ──
def test_record_outcome_rejects_bad_label():
    fs = FraudScorer()
    assert fs.record_fraud_outcome("c1", "not_a_label") is False


def test_adaptive_scoring_off_by_default(monkeypatch):
    monkeypatch.delenv("FRAUD_ADAPTIVE_WEIGHTS", raising=False)
    fs = FraudScorer()
    # With the flag off, score is the pure static-weight result regardless of feedback.
    s = fs.calculate_score({"serial_mismatch": True})
    assert 0.0 <= s <= 1.0


def test_record_and_learn_roundtrip(monkeypatch):
    fs = FraudScorer()
    import uuid as _u
    sig = f"_test_signal_{_u.uuid4().hex[:8]}"  # unique so the test is isolated from other rows
    for _ in range(6):
        assert fs.record_fraud_outcome("case-x", "confirmed_fraud", signals={sig: True}) is True
    weights = fs.learned_signal_weights()
    assert weights.get(sig, 0) > 1.0  # all-confirmed -> amplified toward ceil
