"""Project the governed cart response without recommendation rewrites or automatic confirmation."""
import logging
import os
from typing import Any, Dict, Optional
from src.app.services.chat_turn_projection import _extract_confirmed_slots
from src.app.services.chat_persistence import _store_chat_message, _persist_chat_structured_state

logger = logging.getLogger(__name__)


def _cart_mutation_short_circuit(
    data: Any,
    *,
    q: str,
    uid: str,
    db,
    redis=None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    session_epoch: str | None = None,
    persist_conversation: bool = True,
) -> Optional[Dict[str, Any]]:
    """CART-MUTATION short-circuit (V2 cart lane, extracted for testability): when the suggest
    hop returns a cart_mutation payload (RECOMMEND_CART_SERVE=on), build the MINIMAL chat
    response — the product/answer-quality/copywriting machinery below chat_query is irrelevant
    (and message-REWRITING) for a cart edit. Forwards the C1 card fields verbatim
    (needs_confirmation/plan_id/ops ride inside cart_mutation). Returns None when this turn is
    not a cart mutation. /chat/stream inherits (it emits chat_query's result verbatim)."""
    if not isinstance(data, dict) or data.get("cart_mutation") is None:
        return None
    tid = data.get("decision_trace_id") or data.get("decision_id") or data.get("trace_id")
    msg = str(data.get("assistant_message") or data.get("message") or "").strip()
    try:
        if not persist_conversation:
            raise RuntimeError("temporary_chat")
        _store_chat_message(
            db,
            tenant_id=tenant_id,
            uid=uid,
            session_id=session_id,
            session_epoch=session_epoch,
            role="user",
            content=q,
            trace_id=tid,
        )
        if msg:
            _store_chat_message(
                db,
                tenant_id=tenant_id,
                uid=uid,
                session_id=session_id,
                session_epoch=session_epoch,
                role="assistant",
                content=msg,
                trace_id=tid,
            )
    except Exception as _cm_exc:
        if persist_conversation:
            logger.debug("cart-mutation chat persist skipped: %s", repr(_cm_exc)[:100])
    multi_intent = None
    try:
        enabled = str(os.getenv("MULTI_INTENT_PLANNER_ENABLED", "")).strip().lower() in (
            "1", "true", "yes", "on",
        )
        if not enabled:
            from src.app.feature_flags import get_flags as _get_flags

            enabled = bool(_get_flags().get("MULTI_INTENT_PLANNER_ENABLED", False))
        if enabled:
            from src.app.services.multi_intent_live import plan_live

            multi_intent = plan_live(str(q or ""), str(uid))
    except Exception as exc:
        # A cart action is still bounded by its own confirmation contract. Keep
        # the planner failure visible instead of silently dropping the other
        # obligations from a mixed buyer turn.
        multi_intent = {
            "warnings": [f"multi_intent planner error: {str(exc)[:120]}"],
            "needs_confirmation": True,
            "plan": [],
        }
    response_slots = _extract_confirmed_slots(query=q, response=data)
    persisted_slots = dict(response_slots)
    mutation = data.get("cart_mutation") if isinstance(data.get("cart_mutation"), dict) else {}
    if mutation.get("needs_confirmation"):
        # A proposal is not accepted case state. The authoritative quantity
        # remains the persisted cart line until the apply endpoint commits.
        persisted_slots.pop("order_quantity", None)
        persisted_slots.pop("quantity", None)
    out = {
        "products": [],
        "view_mode": "cards",
        "assistant_message": msg,
        "cart_mutation": data.get("cart_mutation"),
        "cart_updated": bool(data.get("cart_updated")),
        "cart": data.get("cart"),
        "multi_intent": multi_intent,
        "turn_intent": "CART_MUTATE",
        "execution_mode": data.get("execution_mode") or "v2_served",
        "execution_lane": data.get("execution_lane") or "CART_MUTATE",
        "delegation_reason": data.get("delegation_reason"),
        "action_executed": bool(data.get("action_executed")),
        # Read-only case status/summary responses intentionally keep the buyer's
        # current product/cart/procurement panel in place. This is a typed UI
        # contract, not an inference from an empty product list.
        # A cart amendment is an in-place operation on the visible cart/procurement case.  An
        # empty products list is not permission to replace that view with search results.
        "preserve_current_view": True,
        "case_operation": data.get("case_operation"),
        "case_anchor": data.get("case_anchor") if isinstance(data.get("case_anchor"), dict) else None,
        "state_changed": data.get("state_changed"),
        # Bounded delivery/payment amendments are accepted by the recommendation
        # reducer and then committed later by the cart sourcing boundary.  Keep
        # the canonical constraints at the HTTP/SSE edge; dropping them here made
        # the UI acknowledge the amendment while confirming the old requirements.
        "constraints_used": (
            data.get("constraints_used")
            if isinstance(data.get("constraints_used"), dict) else {}
        ),
        "decision_trace_id": tid,
        "trace_id": tid,
        "next_questions": [],
        "confirmed_slots": response_slots,
        "requested_quantity": (
            data.get("requested_quantity")
            if data.get("requested_quantity") is not None
            else response_slots.get("order_quantity")
        ),
        "explanation": (
            data.get("explanation")
            if isinstance(data.get("explanation"), dict) else None
        ),
        "delivery_feasibility": (
            data.get("delivery_feasibility")
            if isinstance(data.get("delivery_feasibility"), dict) else None
        ),
        "case_obligations": (
            data.get("case_obligations")
            if isinstance(data.get("case_obligations"), list) else []
        ),
        "policy_answer": (
            data.get("policy_answer") if isinstance(data.get("policy_answer"), dict) else None
        ),
        "support_handoff": (
            data.get("support_handoff") if isinstance(data.get("support_handoff"), dict) else None
        ),
        "supplier_status": (
            data.get("supplier_status") if isinstance(data.get("supplier_status"), dict) else None
        ),
        "timing_breakdown": (
            data.get("timing_breakdown")
            if isinstance(data.get("timing_breakdown"), dict)
            else {}
        ),
        "blocked": False,
        "needs_human_review": False,
        "security_route": "allow",
    }
    try:
        if not persist_conversation:
            raise RuntimeError("temporary_chat")
        _persist_chat_structured_state(
            redis=redis,
            uid=uid,
            query=q,
            products=[],
            trace_id=str(tid or "") or None,
            assistant_message=msg,
            confirmed_slots=persisted_slots,
            tenant_id=tenant_id,
            session_epoch=session_epoch,
        )
    except Exception:
        if persist_conversation:
            logger.warning("cart-mutation structured-state persistence failed", exc_info=True)
    return out
