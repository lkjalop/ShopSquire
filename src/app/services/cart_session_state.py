"""Invalidate cart-derived conversation state after an authoritative cart clear."""

from __future__ import annotations

from typing import Any

from src.app.services.memory import Memory


_COMMERCIAL_CONSTRAINT_KEYS = {
    "budget_min_cents",
    "budget_max_cents",
    "budget_scope",
    "exact_product_sku",
    "operational_constraints",
    "product_selection_authority",
    "quantity",
    "order_quantity",
    "requested_quantity",
    "total_budget_cents",
}

_CART_STATE_KEYS = {
    "active_pr",
    "active_workflow_lane",
    "case_anchor",
    "last_fulfillment_case",
    "last_product_explanation",
    "product_explanations",
    "last_sourcing_intent",
    "selected_cart_sku",
}


def clear_cart_commercial_state(
    redis: Any,
    *,
    uid: str,
    tenant_id: str,
    session_epoch: str | None,
) -> dict[str, Any]:
    """Clear cart/procurement authority while retaining workload evidence."""
    memory = Memory(redis, tenant_id=tenant_id, session_epoch=session_epoch)
    state = memory.get_structured_state(uid)
    if not isinstance(state, dict) or not state:
        memory.clear_pending_clarification(uid)
        return {}

    cleaned = dict(state)
    # Chat merges `confirmed_slots` from structured state into every new turn,
    # while core also reads `accepted_constraints`. Clearing only the older
    # `constraints` shape lets a prior bulk quantity resurrect on the next Add.
    for container_key in ("constraints", "accepted_constraints", "confirmed_slots"):
        container = cleaned.get(container_key)
        if isinstance(container, dict):
            cleaned[container_key] = {
                key: value
                for key, value in container.items()
                if key not in _COMMERCIAL_CONSTRAINT_KEYS
            }
    for key in _COMMERCIAL_CONSTRAINT_KEYS:
        cleaned.pop(key, None)
    for key in _CART_STATE_KEYS:
        cleaned.pop(key, None)
    cleaned["last_shortlist_skus"] = []
    cleaned["last_node_handle"] = None
    cleaned["last_lane"] = None
    cleaned["cart_cleared"] = True

    memory.set_structured_state(uid, cleaned)
    memory.clear_pending_clarification(uid)
    return cleaned
