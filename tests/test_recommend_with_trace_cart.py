"""_with_trace must PRESERVE the cart-mutation contract fields (V2 cart milestone step 3 glue).

The facade routes every served payload through recommend.py's _with_trace (sanitize → localize →
formatter → trace stamping). None of those stages may strip cart_mutation/cart/cart_updated or
rewrite a cart confirmation into 'no match' prose — if one ever does, the whole cart lane breaks
SILENTLY (chat.py's short-circuit keys on cart_mutation being present). Regression-locked here.
"""
from src.app.routers.recommend import _with_trace


def _cart_payload():
    return {
        "assistant_message": "Done — removed 2 items, set a line to 20.",
        "message": "Done — removed 2 items, set a line to 20.",
        "products": [], "results": [],
        "turn_intent": "CART_MUTATE", "turn_type": "cart_mutate_turn",
        "cart_mutation": {"applied": [{"action": "remove_items", "sku": "LAP-1"}],
                          "rejected": [], "ambiguous": [], "needs_clarification": False},
        "cart": {"items": [{"sku": "LAP-2", "quantity": 20}], "subtotal_cents": 100000},
        "cart_updated": True,
        "degraded": False, "off_catalog": None,
    }


def test_with_trace_preserves_cart_contract_fields():
    out = _with_trace(_cart_payload(), "tid-cart-verify")
    assert out.get("cart_mutation") is not None, "sanitize/formatter stripped cart_mutation"
    assert out.get("cart", {}).get("items"), "cart block stripped"
    assert out.get("cart_updated") is True
    assert out["trace_id"] == "tid-cart-verify"
    assert out["decision_trace_id"] == "tid-cart-verify"


def test_with_trace_does_not_rewrite_cart_message_as_no_match():
    # products=[] on a cart turn must NOT trigger the never-empty 'no match' compose —
    # the cart confirmation is the answer.
    out = _with_trace(_cart_payload(), "tid-cart-verify2")
    msg = str(out.get("assistant_message") or "")
    assert "Done" in msg
    assert "no match" not in msg.lower() and "couldn't find" not in msg.lower()
