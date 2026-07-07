"""Claim-policy signals — deterministic via injected `now`; ACL invariant: signals raise score, never deny."""
from __future__ import annotations

from datetime import datetime, timedelta

from src.app.services.claim_policy import evaluate_claim_policy


NOW = datetime(2026, 7, 7, 12, 0, 0)


def _corr(days_ago: int, total_cents: int = 199900) -> dict:
    return {
        "order_found": True,
        "order_id": "ORD-X",
        "purchased_at": (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S"),
        "total_cents": total_cents,
    }


def _names(signals):
    return [s["signal"] for s in signals]


def test_inside_return_window_no_signals():
    s = evaluate_claim_policy(corroboration=_corr(10), claimed_value_cents=0, now=NOW)
    assert _names(s) == []


def test_outside_return_window_flags_but_mentions_warranty():
    s = evaluate_claim_policy(corroboration=_corr(90), claimed_value_cents=0, now=NOW)
    assert _names(s) == ["outside_return_window"]
    assert "warranty" in s[0]["detail"].lower()   # buyer may still have a valid guarantee claim


def test_outside_warranty_window_routes_to_human_not_denied():
    s = evaluate_claim_policy(corroboration=_corr(400), claimed_value_cents=0, now=NOW)
    assert _names(s) == ["outside_warranty_window"]
    # the ACL invariant lives in the wording the reviewer sees: routed to a human, never auto-denied
    assert "not auto-denied" in s[0]["detail"].lower()


def test_claimed_value_above_order_total_flags():
    s = evaluate_claim_policy(corroboration=_corr(5, total_cents=50000),
                              claimed_value_cents=99900, now=NOW)
    assert "claimed_value_exceeds_order" in _names(s)


def test_claimed_value_within_order_total_clean():
    s = evaluate_claim_policy(corroboration=_corr(5, total_cents=50000),
                              claimed_value_cents=30000, now=NOW)
    assert "claimed_value_exceeds_order" not in _names(s)


def test_off_topic_evidence_flagged_when_images_present():
    # produce labels on an electronics claim → invalid evidence (the apples-photo case)
    s = evaluate_claim_policy(corroboration=_corr(5), claimed_value_cents=0, now=NOW,
                              labels=["apple", "fruit", "food"], ocr_text="", has_images=True)
    assert "invalid_evidence_off_topic" in _names(s)
    assert "photograph" in [x for x in s if x["signal"] == "invalid_evidence_off_topic"][0]["detail"]


def test_no_off_topic_check_without_images():
    s = evaluate_claim_policy(corroboration=_corr(5), claimed_value_cents=0, now=NOW,
                              labels=["apple", "fruit"], has_images=False)
    assert "invalid_evidence_off_topic" not in _names(s)


def test_unknown_purchase_date_no_window_signal():
    s = evaluate_claim_policy(corroboration={"order_found": False}, claimed_value_cents=0, now=NOW)
    assert s == []
