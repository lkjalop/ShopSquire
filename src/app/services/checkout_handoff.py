"""Checkout handoff — advisory-only purchase-intent stage (extracted suggest() leaf).

David's autonomy rule: the AI never touches money directly. It stays in advisory mode and,
when the buyer signals intent to buy, emits a STRUCTURED checkout_action that routes them to
the deterministic payment flow (order create -> Stripe). This is the boundary between
inference (AI) and execution (deterministic): the AI proposes the handoff; it never settles.

This is a CORE module — vertical-blind, pure transform, never raises. The first leaf lifted
out of recommend.py::suggest() to prove the stage-decomposition pattern end-to-end.
"""
from __future__ import annotations

from typing import Any, Dict

from src.app.services.recommend_context import RecommendContext

# Generic purchase-intent phrases (vertical-blind — no product flavour).
CHECKOUT_INTENT_PHRASES = (
    "buy this", "buy now", "buy it", "purchase this", "purchase it",
    "add to cart", "add to my cart", "add it to cart",
    "i want to buy", "i'll buy", "i want this one",
    "i'll take it", "i'll take this", "i'll get this",
    "get this one", "order this", "place order", "proceed to checkout",
    "go to checkout", "checkout now", "i'm ready to buy",
    "ready to purchase", "take my money", "how do i buy",
    "how to buy", "how to order", "where do i buy",
    "can i buy", "let me buy", "i want to order",
)


def detect_checkout_intent(query: str | None) -> bool:
    """Return True if the query contains a clear purchase-intent signal."""
    q = str(query or "").lower().strip()
    if not q:
        return False
    return any(phrase in q for phrase in CHECKOUT_INTENT_PHRASES)


def apply_checkout_handoff(payload: Dict[str, Any], ctx: RecommendContext) -> Dict[str, Any]:
    """If the buyer signals purchase intent, attach a structured checkout_action that routes
    them to the deterministic payment flow. Advisory only — the AI never settles money. Pure
    transform on the response payload; swallows all errors so it can never break a response."""
    try:
        if not detect_checkout_intent(ctx.query):
            return payload
        results = payload.get("results") or []
        top = results[0] if results else {}
        top_sku = str(top.get("sku") or "").strip()
        top_price = top.get("price_cents") or (
            int(float(top.get("price") or 0) * 100) if top.get("price") else None
        )
        payload["checkout_action"] = {
            "intent": "checkout",
            "suggested_sku": top_sku or None,
            "suggested_price_cents": top_price,
            "endpoint": "/api/v1/payments/checkout-initiate",
            "order_create_endpoint": "/api/v1/orders/create",
            "message": (
                f"Ready to buy {top.get('name', 'this item')}? "
                "Create an order and proceed to checkout."
            ) if top_sku else "Ready to proceed? Create an order and go to checkout.",
            "flow": [
                {"step": 1, "action": "POST /api/v1/orders/create", "description": "Create order record with SKUs"},
                {"step": 2, "action": "POST /api/v1/payments/checkout-initiate", "description": "Initiate Stripe payment"},
                {"step": 3, "action": "Stripe Elements (client-side)", "description": "Collect and confirm payment"},
            ],
        }
    except Exception:
        pass
    return payload
