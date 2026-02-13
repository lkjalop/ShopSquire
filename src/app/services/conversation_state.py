from typing import Optional


class ConversationState:
    """Lightweight conversation state helper for intent->state mapping.

    This is intentionally simple: it provides deterministic mapping from
    high-level NLP intents to a conversation state label (browse/compare/checkout/support).
    It also exposes a helper to merge into existing KV stores.
    """

    DEFAULT = "browse"

    @staticmethod
    def infer_from_intent(intent: Optional[str]) -> str:
        if not intent:
            return ConversationState.DEFAULT
        i = intent.lower()
        if i in ("compare_two_specific", "compare_multiple_shortlist", "compare") or "compare" in i:
            return "compare"
        if i in ("procurement_intent", "bulk_discount_inquiry"):
            return "procurement"
        if i in ("order_status", "return_request", "refund_request", "support") or "support" in i:
            return "support"
        if i in ("product_discovery_open_ended", "which_should_i_buy", "best_overall_in_category", "product_search"):
            return "browse"
        if i in ("procurement_intent",):
            return "procurement"
        # default fallback
        return ConversationState.DEFAULT

    @staticmethod
    def apply_to_kv(kv: dict, state: str) -> dict:
        try:
            meta = kv.get("prefs_meta") or {}
            meta["conversation_state"] = {"value": state, "ts": __import__("time").time()}
            kv["prefs_meta"] = meta
            kv["conversation_state"] = state
        except Exception:
            kv["conversation_state"] = state
        return kv
