"""Availability / fulfilment agent (agnostic CORE).

Answers the question the decomposer now surfaces — "can we fulfil N units by day D?" — from current
stock + supplier lead-time, and (optionally) drafts a HUMAN-GATED reorder for any shortfall.

Governance: the agent INFERS feasibility and PROPOSES a draft; it NEVER sends a PO (the reorder is
draft-first, status 'awaiting_human_approval', via reorder_supplier_flow). Pure orchestration with
injectable deps (testable); all vertical vocabulary lives in the data/services it calls, never here —
so this module is vertical-blind and belongs in the no-flavour core.

It returns STRUCTURED data only (no prose); the natural-language line is the caller's job (Step 4).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional


def _default_stock_fn(skus: List[str]) -> Dict[str, int]:
    # the inventory-source adapter: canonical commerce_catalog stock when COMMERCE_CATALOG_ENABLED,
    # else the legacy batch_stock_levels (per-sku overlay — see services/inventory_source.py).
    from src.app.services.inventory_source import stock_levels
    return stock_levels(skus) or {}


def _default_lead_time_fn(sku: str) -> int:
    """Supplier lead-time (days) for a SKU, from the best-supplier lookup; 7-day fallback.
    Returns a value on any failure (NOT a silent pass), so it stays off the silent-except ratchet."""
    try:
        from src.app.services.inventory_agent import InventoryAgent
        sup = InventoryAgent()._get_best_supplier(sku) or {}
        lt = sup.get("lead_time_days") or sup.get("lead_time")
        return int(lt) if lt else 7
    except Exception:
        return 7


def _default_reorder_fn(
    sku: str,
    current_stock: int,
    reorder_point: int,
    *,
    tenant_id: str,
) -> Dict[str, Any]:
    from src.app.services.reorder_supplier_flow import plan_reorder_with_supplier_draft
    return plan_reorder_with_supplier_draft(
        sku=sku,
        current_stock=int(current_stock),
        reorder_point=int(reorder_point),
        tenant_id=tenant_id,
    )


def assess_availability(
    skus: List[str],
    order_quantity: int,
    horizon_days: Optional[int] = None,
    *,
    stock_fn: Optional[Callable[[List[str]], Dict[str, int]]] = None,
    lead_time_fn: Optional[Callable[[str], int]] = None,
    reorder_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    draft_reorder: bool = False,
    tenant_id: str = "default",
) -> Dict[str, Any]:
    """Assess fulfilment of ``order_quantity`` units of the PRIMARY candidate (skus[0]) within
    ``horizon_days``. Fast by default (stock + lead-time only); set ``draft_reorder=True`` to also
    create the human-gated supplier draft for the shortfall (heavier — forecasts demand).

    Returns: {applicable, sku, requested_qty, in_stock, shortfall, eta_days, feasible, fulfilment,
              horizon_days, lead_time_days?, reorder_draft?}. ``feasible`` is None when no horizon was
              stated (report the ETA, don't judge). Never raises.
    """
    skus = [str(s) for s in (skus or []) if str(s).strip()]
    n = int(order_quantity or 0)
    if not skus or n <= 0:
        return {"applicable": False}

    stock_fn = stock_fn or _default_stock_fn
    lead_time_fn = lead_time_fn or _default_lead_time_fn

    primary = skus[0]
    stock_map = stock_fn(skus) or {}
    in_stock = int(stock_map.get(primary, 0) or 0)
    shortfall = max(0, n - in_stock)

    result: Dict[str, Any] = {
        "applicable": True,
        "sku": primary,
        "requested_qty": n,
        "in_stock": in_stock,
        "shortfall": shortfall,
        "horizon_days": horizon_days,
    }

    if shortfall <= 0:
        result.update({"feasible": True, "eta_days": 0, "fulfilment": "in_stock"})
        # Per-SKU allocation evidence so "all N in stock" is auditable (which SKU, how many).
        result["allocation"] = [{"sku": primary, "from_stock": n, "from_reorder": 0, "eta_days": 0}]
        return result

    lead = int(lead_time_fn(primary) or 7)
    result["lead_time_days"] = lead
    result["eta_days"] = lead
    # Per-SKU allocation evidence: how the quantity is covered (current stock vs supplier reorder),
    # so the availability claim is auditable in the payload + decision trace, not just asserted.
    result["allocation"] = [{
        "sku": primary, "from_stock": in_stock, "from_reorder": shortfall, "eta_days": lead,
    }]
    if horizon_days is not None:
        result["feasible"] = lead <= int(horizon_days)
        result["fulfilment"] = "reorder_within_horizon" if result["feasible"] else "reorder_exceeds_horizon"
    else:
        result["feasible"] = None  # no horizon stated → report ETA, don't judge feasibility
        result["fulfilment"] = "reorder_required"

    if draft_reorder:
        if reorder_fn is None:
            reorder_fn = lambda **kwargs: _default_reorder_fn(
                **kwargs, tenant_id=tenant_id
            )
        try:
            draft = reorder_fn(sku=primary, current_stock=in_stock, reorder_point=n) or {}
            result["reorder_draft"] = {
                "status": draft.get("status", "awaiting_human_approval"),
                "low_stock": draft.get("low_stock"),
            }
        except Exception as exc:
            result["reorder_draft"] = {"status": "draft_unavailable", "reason": str(exc)[:120]}

    return result


def availability_summary_line(verdict: Dict[str, Any]) -> str:
    """Render an assess_availability() verdict into ONE plain sentence for the assistant message.
    Pure formatting — numbers + neutral terms only (no vertical vocabulary), so it stays in core."""
    if not isinstance(verdict, dict) or not verdict.get("applicable"):
        return ""
    n = int(verdict.get("requested_qty") or 0)
    in_stock = int(verdict.get("in_stock") or 0)
    short = int(verdict.get("shortfall") or 0)
    eta = verdict.get("eta_days")
    horizon = verdict.get("horizon_days")
    ful = verdict.get("fulfilment")
    if ful == "in_stock":
        return f"On availability: all {n} are in stock now."
    eta_txt = f"~{int(eta)} days" if eta else "a short lead time"
    base = f"On availability: {in_stock} in stock now"
    if ful == "reorder_within_horizon":
        return f"{base}; the other {short} in {eta_txt} — {n} within {int(horizon)} days is feasible."
    if ful == "reorder_exceeds_horizon":
        return (f"{base}; the other {short} would take {eta_txt}, beyond your {int(horizon)}-day window "
                f"— I can draft a supplier reorder for your approval.")
    return f"{base}; the other {short} in {eta_txt} via supplier (a draft reorder is available on request)."


def availability_allocation_line(verdict: Dict[str, Any]) -> str:
    """Auditable per-SKU allocation evidence ("SKU-X: 5 of 10 from stock, 5 via reorder (ETA 7d)").
    Pure formatting from the structured allocation; empty when there's nothing to attribute."""
    if not isinstance(verdict, dict):
        return ""
    rows = verdict.get("allocation")
    if not isinstance(rows, list) or not rows:
        return ""
    parts: List[str] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        sku = str(r.get("sku") or "")
        from_stock = int(r.get("from_stock") or 0)
        from_reorder = int(r.get("from_reorder") or 0)
        total = from_stock + from_reorder
        seg = f"{sku}: {from_stock} of {total} from stock"
        if from_reorder > 0:
            eta = r.get("eta_days")
            eta_txt = f" (ETA ~{int(eta)}d)" if eta else ""
            seg += f", {from_reorder} via reorder{eta_txt}"
        parts.append(seg)
    return " | ".join(parts)
