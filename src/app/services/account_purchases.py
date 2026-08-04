"""Unified customer purchases + tracking read model (agnostic CORE).

A customer's activity is split across two systems that never joined in a customer view: consumer
ORDERS (checkout purchases, orders table) and PROCUREMENT CASES (bulk/RFQ-sourced, fulfillment_
case_version keyed by order_group_id). A B2B buyer's "purchases" therefore lived in two places.

This unions them into ONE newest-first timeline, each entry carrying its status + tracking, plus a
per-order tracking read (status + carrier + transition history). Pure reads; best-effort; never
raises. Vertical-blind (order/case ids, cents, opaque statuses — no product vocabulary).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text


def _order_ids_for(db, *, uid: Optional[str], customer_id: Optional[str]) -> List[str]:
    """The order ids belonging to a customer — by uid (order_sessions) OR customer_id (orders)."""
    ids: List[str] = []
    try:
        if uid:
            rows = db.execute(text("SELECT order_id FROM order_sessions WHERE uid = :u"), {"u": uid}).fetchall()
            ids.extend(str(r[0]) for r in rows if r[0])
        if customer_id:
            rows = db.execute(text("SELECT id FROM orders WHERE customer_id = :c"), {"c": customer_id}).fetchall()
            ids.extend(str(r[0]) for r in rows if r[0])
    except Exception:
        return list(dict.fromkeys(ids))
    return list(dict.fromkeys(ids))  # dedupe, preserve order


def _consumer_order(db, order_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = db.execute(text("SELECT id, total_cents, currency, status, tracking_number, carrier, created_at "
                            "FROM orders WHERE id = :o LIMIT 1"), {"o": order_id}).fetchone()
    except Exception:
        return None
    if not r:
        return None
    return {"kind": "order", "id": r[0], "total_cents": r[1], "currency": r[2] or "USD",
            "status": r[3], "tracking_number": r[4], "carrier": r[5], "created_at": str(r[6] or ""),
            "sort_key": str(r[6] or "")}


def _procurement_entries(db, order_id: str) -> List[Dict[str, Any]]:
    """The procurement cases sourced for this order (supplier RFQ side), as timeline entries."""
    try:
        from src.app.services.fulfillment.cart_commitment import list_order_cases
        cases = list_order_cases(db, order_id)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for c in cases or []:
        if c.get("superseded"):
            continue  # only the live version of each case in the customer view
        out.append({"kind": "procurement", "id": c.get("case_id"), "order_id": order_id,
                    "status": c.get("state"), "supplier_domain": (c.get("draft") or {}).get("recipient_domain"),
                    "created_at": str(c.get("valid_from") or ""), "sort_key": str(c.get("valid_from") or "")})
    return out


def unified_purchases(db, *, uid: Optional[str] = None, customer_id: Optional[str] = None,
                      limit: int = 20) -> List[Dict[str, Any]]:
    """One newest-first timeline of a customer's consumer orders + procurement cases. Best-effort."""
    if db is None or not (uid or customer_id):
        return []
    order_ids = _order_ids_for(db, uid=uid, customer_id=customer_id)
    timeline: List[Dict[str, Any]] = []
    for oid in order_ids:
        co = _consumer_order(db, oid)
        if co:
            timeline.append(co)
        timeline.extend(_procurement_entries(db, oid))
    timeline.sort(key=lambda e: str(e.get("sort_key") or ""), reverse=True)
    for e in timeline:
        e.pop("sort_key", None)
    return timeline[: max(1, int(limit))]


def order_tracking(db, order_id: str, *, uid: Optional[str] = None, customer_id: Optional[str] = None,
                   guest_email_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Tracking read for ONE order, scoped to the requester so a customer only sees their own:
    member by uid/customer_id, guest by email hash. Returns status + tracking + carrier, or None if
    the order isn't the requester's. Best-effort."""
    if db is None or not order_id:
        return None
    try:
        r = db.execute(text("SELECT id, status, tracking_number, carrier, customer_id, guest_email_hash, "
                            "total_cents, currency, created_at, updated_at FROM orders WHERE id = :o LIMIT 1"),
                       {"o": order_id}).fetchone()
    except Exception:
        return None
    if not r:
        return None
    owner_ok = False
    if customer_id and str(r[4] or "") == str(customer_id):
        owner_ok = True
    if guest_email_hash and str(r[5] or "") == str(guest_email_hash):
        owner_ok = True
    if uid and not owner_ok:
        try:
            hit = db.execute(text("SELECT 1 FROM order_sessions WHERE uid = :u AND order_id = :o LIMIT 1"),
                             {"u": uid, "o": order_id}).fetchone()
            owner_ok = bool(hit)
        except Exception:
            owner_ok = False
    if not owner_ok:
        return None
    return {"order_id": r[0], "status": r[1], "tracking_number": r[2], "carrier": r[3],
            "total_cents": r[6], "currency": r[7] or "USD",
            "created_at": str(r[8] or ""), "updated_at": str(r[9] or "")}
