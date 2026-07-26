"""Demand -> supplier reorder flow (bounded, draft-first). CORE / vertical-blind.

One demo-able flow that chains the existing pieces under bounded autonomy:

    low stock?  ->  forecast demand  ->  propose reorder qty  ->  DRAFT supplier message  ->  HUMAN APPROVAL

It NEVER sends. The draft is returned with status 'awaiting_human_approval'; the actual send still
goes through supplier_communication.dispatch_supplier_message (execution_gate + MAESTRO + recipient
allowlist). This is the inventory-autonomy story: the AI proposes and drafts, a human approves.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional


def plan_reorder_with_supplier_draft(
    *,
    sku: str,
    current_stock: int,
    reorder_point: int,
    supplier_name: str = "Supplier",
    supplier_email: str = "",
    cover_days: int = 30,
    forecast_fn: Optional[Callable[..., Any]] = None,
    draft_fn: Optional[Callable[..., Any]] = None,
    templates: Optional[Dict[str, Any]] = None,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Run the bounded demand->supplier flow for one SKU. Returns:
      * {low_stock: False, status: 'ok_no_reorder'} when stock is above the reorder point;
      * {low_stock: True, forecast, proposed_qty, draft, status: 'awaiting_human_approval'} otherwise.
    Draft-first: NEVER sends. forecast_fn / draft_fn are injected (lazy real defaults) for testability.
    Never raises. A forecast failure returns a degraded result and must not create a
    zero-quantity supplier request."""
    on_hand = int(current_stock or 0)
    low = on_hand <= int(reorder_point or 0)
    if not low:
        return {
            "sku": sku, "low_stock": False, "status": "ok_no_reorder",
            "reason": f"stock {on_hand} above reorder point {int(reorder_point or 0)}",
        }

    # 1) Forecast demand over the cover window.
    if forecast_fn is None:
        from src.app.services.demand_forecast import DemandForecaster
        forecast_fn = DemandForecaster(tenant_id=tenant_id).forecast_sku
    projected = 0.0
    try:
        fc = forecast_fn(sku, cover_days)
        daily = getattr(fc, "daily", None)
        if daily is None and isinstance(fc, dict):
            daily = fc.get("daily")
        projected = sum(float((d or {}).get("mean") or 0.0) for d in (daily or [])[: int(cover_days)])
    except Exception as exc:
        return {
            "sku": sku,
            "low_stock": True,
            "forecast": None,
            "proposed_qty": None,
            "draft": None,
            "status": "degraded_no_proposal",
            "reason": "forecast_unavailable",
            "error_type": type(exc).__name__,
        }

    # 2) Propose a reorder quantity (cover projected demand minus what's on hand; never negative).
    proposed_qty = max(0, int(math.ceil(projected)) - on_hand)
    if proposed_qty <= 0:
        return {
            "sku": sku,
            "low_stock": True,
            "forecast": {
                "cover_days": int(cover_days),
                "projected_demand": round(projected, 2),
            },
            "proposed_qty": 0,
            "draft": None,
            "status": "no_reorder_required",
            "reason": "forecast_does_not_exceed_available_stock",
        }

    # 3) Draft the supplier message (never sends).
    if draft_fn is None:
        from src.app.services.supplier_communication import draft_supplier_message as draft_fn
        if templates is None:
            try:
                from src.app.platform.store_profile import profile_slot
                templates = profile_slot("supplier_message_templates", default=None)
            except Exception:
                templates = None
    draft = draft_fn(
        kind="reorder",
        supplier_name=supplier_name,
        supplier_email=supplier_email,
        item=f"{sku} (qty {proposed_qty})",
        details=f"Projected {int(cover_days)}-day demand ~{int(math.ceil(projected))} units; {on_hand} on hand.",
        templates=templates,
    )

    return {
        "sku": sku,
        "low_stock": True,
        "forecast": {"cover_days": int(cover_days), "projected_demand": round(projected, 2)},
        "proposed_qty": proposed_qty,
        "draft": draft.to_dict() if hasattr(draft, "to_dict") else draft,
        "status": "awaiting_human_approval",
        "note": "draft only — sending requires human approval via supplier_communication.dispatch (gated)",
    }
