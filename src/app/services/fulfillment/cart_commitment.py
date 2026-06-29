"""Cart-commitment materialization (agnostic CORE) — GATE 1 at the buyer's COMMITMENT, not on a query.

The recommend stage leaves the buyer's sourcing intent FLUID (a preview, no durable case) under
FULFILLMENT_DEFER_TO_CART. The single commitment boundary is the order/cart confirmation: when the buyer
CONFIRMS the order, the shortfall lines materialize into durable procurement cases — one per supplier group
— each waiting at GATE 1 (AWAITING_BUYER_COMMITMENT; no supplier is contacted).

Two safety properties this module owns:
  - IDEMPOTENCY: keyed on the order id (order_group_id = "order-<order_id>"). A double-submitted confirm
    returns the SAME cases instead of creating duplicates (the consumer-behavior "two POs" bug).
  - VERTICAL-BLIND: lines are opaque {item_ref, requested_qty, in_stock?}; shortfall is pure arithmetic;
    supplier routing/terms come from order_split (which reads the StoreProfile). No product vocabulary.

Read-only planning + case creation are delegated to order_split; this module is the commitment seam only.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.services.fulfillment.order_split import (
    create_grouped_cases, emit_split_trace, plan_order_split, resolve_line_skus)

logger = logging.getLogger("shopsquire.cart_commitment")


def order_group_id_for(order_id: str) -> Optional[str]:
    """The deterministic order_group_id stamped onto every case materialized for this order — the
    idempotency key. None for a blank order id."""
    oid = str(order_id or "").strip()
    return f"order-{oid}" if oid else None


def _already_materialized(db, order_group_id: str, tenant_id: str = "default") -> List[str]:
    """Idempotency probe: the case ids already materialized for this order's commitment, found by the
    order_group_id stamped into the case state_json. A re-confirm (double-submit) returns these instead of
    creating duplicates. Best-effort; [] on any error (the caller then proceeds to create)."""
    if db is None or not order_group_id:
        return []
    try:
        from src.app.services.fulfillment.repository import ensure_tables
        ensure_tables(db)
        # state_json is JSON TEXT; match the order_group_id value loosely so JSON separator spacing never
        # breaks the probe. Only the OPEN (valid_to IS NULL) version of each case counts.
        pat = f'%"order_group_id"%{order_group_id}%'
        rows = db.execute(text(
            "SELECT DISTINCT case_id FROM fulfillment_case_version "
            "WHERE tenant_id=:t AND valid_to IS NULL AND state_json LIKE :p"),
            {"t": str(tenant_id or "default"), "p": pat}).fetchall()
        return [str(r[0]) for r in (rows or []) if r and r[0]]
    except Exception as exc:
        logger.debug("_already_materialized probe failed for %s: %s", order_group_id, exc)
        return []


def _line_signature(pairs) -> frozenset:
    """An order-independent signature of {item_ref → requested_qty} so a re-confirm can be told apart:
    identical lines = a double-submit (idempotent); different lines = a real AMENDMENT (the buyer changed
    their mind after committing) → supersession, not a silent no-op."""
    sig = set()
    for item_ref, qty in pairs:
        ir = str(item_ref or "").strip()
        if ir:
            sig.add((ir, int(qty or 0)))
    return frozenset(sig)


def _materialized_signature(db, case_ids: List[str], tenant_id: str = "default") -> frozenset:
    """The {item_ref → requested_qty} signature already on the materialized cases (read from each case's
    stored order_lines), so it can be compared against an incoming confirm."""
    from src.app.services.fulfillment.repository import current_version
    pairs = []
    for cid in case_ids:
        cur = current_version(db, cid, tenant_id)
        for ln in ((cur.state_json.get("order_lines") if cur and isinstance(cur.state_json, dict) else None) or []):
            if isinstance(ln, dict):
                pairs.append((ln.get("item_ref"), ln.get("quantity")))
    return _line_signature(pairs)


def materialize_cases_for_order(db, *, order_id: str, lines: List[Dict[str, Any]],
                                uid: Optional[str] = None, uid_hash: Optional[str] = None,
                                trace_id: Optional[str] = None, tenant_id: str = "default",
                                now_iso: Optional[str] = None) -> Dict[str, Any]:
    """GATE 1 at the COMMITMENT boundary: turn a confirmed order's shortfall lines into durable procurement
    cases (one per supplier group), idempotently keyed on the order id.

    ``lines`` are vertical-blind dicts {item_ref|sku, requested_qty|quantity, in_stock?}. A line needs
    sourcing only when requested_qty > in_stock; fully-in-stock lines are fulfilled from stock and never
    create a case. Re-confirming the same order returns the SAME cases (idempotent). No supplier is
    contacted. Returns {order_group_id, case_count, cases, idempotent}."""
    group_id = order_group_id_for(order_id)
    if not group_id or db is None:
        return {"order_group_id": group_id, "case_count": 0, "cases": [], "idempotent": False}

    resolved = resolve_line_skus(db, lines, tenant_id=tenant_id)
    # only the lines we cannot fill from stock need sourcing (requested > in_stock).
    sourcing = [l for l in resolved
                if int(l.get("requested_qty") or 0) > int(l.get("in_stock") or 0)]

    existing = _already_materialized(db, group_id, tenant_id=tenant_id)
    if existing:
        # this order already materialized — distinguish a double-submit from a real amendment.
        incoming_sig = _line_signature((l.get("item_ref"), l.get("requested_qty")) for l in sourcing)
        existing_sig = _materialized_signature(db, existing, tenant_id=tenant_id)
        if incoming_sig == existing_sig:
            return {"order_group_id": group_id, "case_count": len(existing),
                    "cases": [{"case_id": c} for c in existing], "idempotent": True}
        # the buyer changed their mind AFTER committing this order — the lines differ. Do NOT silently
        # return the stale cases and do NOT duplicate; signal that supersession is required (Phase 4). The
        # caller surfaces amend_required so the existing cases can be superseded under a deliberate action.
        return {"order_group_id": group_id, "case_count": len(existing),
                "cases": [{"case_id": c} for c in existing], "idempotent": False,
                "amend_required": True, "reason": "order_lines_changed"}

    if not sourcing:
        return {"order_group_id": group_id, "case_count": 0, "cases": [], "idempotent": False}

    plan = plan_order_split(db, lines=sourcing, tenant_id=tenant_id)
    if not (plan.get("groups") or []):
        return {"order_group_id": group_id, "case_count": 0, "cases": [], "idempotent": False}

    emit_split_trace(trace_id, plan=plan)
    created = create_grouped_cases(db, plan=plan, uid=uid, uid_hash=uid_hash, trace_id=trace_id,
                                   order_group_id=group_id, now_iso=now_iso)
    created["idempotent"] = False
    return created
