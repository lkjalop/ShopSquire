"""Characterization parity — checkout-handoff leaf extracted from recommend.py::suggest().

Pins the EXACT behaviour of the inline block that was lifted out: intent detection on the
same phrase set, the same checkout_action shape/endpoints, top-result SKU/price derivation,
and the advisory-only contract (AI emits a handoff, never a money action).
"""
from __future__ import annotations

import pytest

from src.app.services.checkout_handoff import (
    CHECKOUT_INTENT_PHRASES,
    apply_checkout_handoff,
    detect_checkout_intent,
)
from src.app.services.recommend_context import RecommendContext


@pytest.mark.parametrize("q", ["buy this now", "I want to buy this one", "proceed to checkout", "TAKE MY MONEY"])
def test_intent_detected(q):
    assert detect_checkout_intent(q) is True


@pytest.mark.parametrize("q", ["", None, "what is the best laptop", "compare these two"])
def test_intent_not_detected(q):
    assert detect_checkout_intent(q) is False


def test_no_handoff_without_intent():
    payload = {"results": [{"sku": "X1", "price_cents": 99900, "name": "Thing"}]}
    out = apply_checkout_handoff(payload, RecommendContext(query="show me options"))
    assert "checkout_action" not in out


def test_handoff_shape_with_top_result():
    payload = {"results": [{"sku": "ABC", "price_cents": 150000, "name": "Widget"}]}
    out = apply_checkout_handoff(payload, RecommendContext(query="buy now"))
    ca = out["checkout_action"]
    assert ca["intent"] == "checkout"
    assert ca["suggested_sku"] == "ABC"
    assert ca["suggested_price_cents"] == 150000
    assert ca["endpoint"] == "/api/v1/payments/checkout-initiate"
    assert ca["order_create_endpoint"] == "/api/v1/orders/create"
    assert "Widget" in ca["message"]
    assert [s["step"] for s in ca["flow"]] == [1, 2, 3]


def test_price_derived_from_dollars_when_no_cents():
    payload = {"results": [{"sku": "S2", "price": 1234.0, "name": "N"}]}
    out = apply_checkout_handoff(payload, RecommendContext(query="i'll take it"))
    assert out["checkout_action"]["suggested_price_cents"] == 123400


def test_handoff_with_empty_results_is_generic():
    out = apply_checkout_handoff({"results": []}, RecommendContext(query="how do i buy"))
    ca = out["checkout_action"]
    assert ca["suggested_sku"] is None
    assert ca["suggested_price_cents"] is None
    assert ca["message"] == "Ready to proceed? Create an order and go to checkout."


def test_advisory_only_never_settles_money():
    # The AI may only emit a handoff to a deterministic endpoint — never a settled order/refund.
    out = apply_checkout_handoff({"results": []}, RecommendContext(query="buy it"))
    ca = out["checkout_action"]
    assert ca["intent"] == "checkout"  # proposal, not execution
    assert all("create" in s["action"].lower() or "stripe" in s["action"].lower()
               or "payments" in s["action"].lower() for s in ca["flow"])


def test_pure_transform_never_raises_on_garbage():
    # Swallows malformed payloads — can never break a /suggest response.
    assert apply_checkout_handoff({"results": "not-a-list"}, RecommendContext(query="buy now")) is not None


def test_phrase_set_is_flavour_free():
    # No product/brand flavour in the intent phrases (agnostic core invariant).
    joined = " ".join(CHECKOUT_INTENT_PHRASES).lower()
    for flavour in ("rtx", "laptop", "macbook", "gaming", "gpu"):
        assert flavour not in joined
