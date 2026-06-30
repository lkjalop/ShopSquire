"""Three-way match (agnostic CORE) — the core AP control: PO = goods-receipt = invoice before payment.

Enterprise accounts-payable will not pay an invoice unless it reconciles against the purchase order AND the
goods actually received: quantities agree (within tolerance) and the invoiced amount matches the PO amount
(within a small percentage). This module is the pure reconciliation; the workflow gates COMPLETION (payment)
on it when FULFILLMENT_THREE_WAY_MATCH_ENABLED.

Vertical-blind: quantities + cents only — no product vocabulary. Pure; never raises.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def match(po: Optional[Dict[str, Any]], goods_receipt: Optional[Dict[str, Any]],
          invoice: Optional[Dict[str, Any]], *, qty_tolerance: int = 0,
          amount_tolerance_pct: float = 0.02) -> Dict[str, Any]:
    """Reconcile PO ↔ goods-receipt ↔ invoice. All three documents must be present, the three quantities
    must agree within ``qty_tolerance``, and the invoiced amount must match the PO amount within
    ``amount_tolerance_pct``. Returns {matched, mismatches:[...], po_qty, receipt_qty, invoice_qty,
    po_amount_cents, invoice_amount_cents}."""
    po = po or {}
    gr = goods_receipt or {}
    inv = invoice or {}
    po_qty = _int(po.get("quantity"))
    rcv_qty = _int(gr.get("quantity"))
    inv_qty = _int(inv.get("quantity"))
    po_amt = _int(po.get("total_amount_cents"))
    inv_amt = _int(inv.get("amount_cents") if inv.get("amount_cents") is not None else inv.get("total_amount_cents"))

    mismatches = []
    if not po:
        mismatches.append("missing_po")
    if not gr:
        mismatches.append("missing_goods_receipt")
    if not inv:
        mismatches.append("missing_invoice")
    if not mismatches:  # only compare numbers once all three docs exist
        tol = max(0, int(qty_tolerance))
        if abs(po_qty - rcv_qty) > tol:
            mismatches.append(f"qty_po_vs_receipt:{po_qty}!={rcv_qty}")
        if abs(po_qty - inv_qty) > tol:
            mismatches.append(f"qty_po_vs_invoice:{po_qty}!={inv_qty}")
        if po_amt > 0:
            amt_tol = po_amt * max(0.0, float(amount_tolerance_pct))
            if abs(po_amt - inv_amt) > amt_tol:
                mismatches.append(f"amount_po_vs_invoice:{po_amt}!={inv_amt}")
    return {"matched": not mismatches, "mismatches": mismatches,
            "po_qty": po_qty, "receipt_qty": rcv_qty, "invoice_qty": inv_qty,
            "po_amount_cents": po_amt, "invoice_amount_cents": inv_amt}


def match_for_case(state_json: Dict[str, Any], *, qty_tolerance: int = 0,
                   amount_tolerance_pct: float = 0.02) -> Dict[str, Any]:
    """Convenience: read PO / goods_receipt / invoice off a case's state_json and reconcile."""
    sj = state_json or {}
    return match(sj.get("purchase_order"), sj.get("goods_receipt"), sj.get("invoice"),
                 qty_tolerance=qty_tolerance, amount_tolerance_pct=amount_tolerance_pct)
