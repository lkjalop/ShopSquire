from __future__ import annotations

import json
from typing import Any, Dict, Iterable

from sqlalchemy import text

from src.app.routers.approvals import enqueue_approval


def _load_bundle_approval_rows(db) -> list[dict[str, Any]]:
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    """
                    SELECT id, payload, status, created_at, approved_at
                    FROM approvals
                    WHERE capability = 'bundle_discount'
                    ORDER BY created_at DESC
                    """
                )
            ).mappings().all()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for row in rows or []:
        payload = row.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}
        out.append(
            {
                "id": row.get("id"),
                "status": str(row.get("status") or "pending"),
                "created_at": row.get("created_at"),
                "approved_at": row.get("approved_at"),
                "payload": payload,
            }
        )
    return out


def _approval_expired(row: dict[str, Any]) -> bool:
    """TTL guard: an approval older than BUNDLE_APPROVAL_TTL_HOURS (default 24) no longer binds.
    Fixes the stale-state demo bug where a 20%-approved bundle from a PREVIOUS session kept
    re-applying to the same per-uid cart forever ('-$17,627 discount I didn't select')."""
    import datetime as _dt
    import os as _os
    try:
        ttl_h = float(_os.getenv("BUNDLE_APPROVAL_TTL_HOURS", "24") or 24)
    except (TypeError, ValueError):
        ttl_h = 24.0
    if ttl_h <= 0:
        return False  # TTL disabled
    stamp = row.get("approved_at") or row.get("created_at")
    if not stamp:
        return False
    try:
        ts = _dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.timezone.utc)
        return (_dt.datetime.now(_dt.timezone.utc) - ts).total_seconds() > ttl_h * 3600
    except (TypeError, ValueError):
        return False


def find_bundle_approval(db, *, cart_id: str) -> dict[str, Any] | None:
    cart = str(cart_id or "").strip()
    if not cart:
        return None
    for row in _load_bundle_approval_rows(db):
        payload = row.get("payload") or {}
        if str(payload.get("cart_id") or "").strip() == cart:
            if _approval_expired(row):
                return None  # stale — a fresh bundle must re-request approval
            return row
    return None


def expire_bundle_approvals_for_cart(db, *, cart_id: str) -> int:
    """Explicitly retire a cart's bundle approvals (called when the buyer CLEARS the cart — a cleared
    cart is a new shopping intent; yesterday's approved discount must not ride along). Returns rows
    updated; best-effort."""
    cart = str(cart_id or "").strip()
    if not cart:
        return 0
    try:
        res = db.execute(
            text("UPDATE approvals SET status='expired' WHERE capability='bundle_discount' "
                 "AND status IN ('pending','approved') AND payload LIKE :pat"),
            {"pat": f'%"cart_id": "{cart}"%'},
        )
        db.commit()
        return int(getattr(res, "rowcount", 0) or 0)
    except Exception:
        return 0


def ensure_bundle_discount_approval(
    db,
    *,
    cart_id: str,
    uid: str,
    bundle_savings: Dict[str, Any],
    items: Iterable[Dict[str, Any]],
    created_by: str | None = None,
) -> str | None:
    existing = find_bundle_approval(db, cart_id=cart_id)
    if existing and existing.get("status") in {"pending", "approved", "rejected"}:
        return str(existing.get("id") or "")

    payload = {
        "cart_id": cart_id,
        "uid": uid,
        "requested_discount_percent": bundle_savings.get("requested_discount_percent"),
        "subtotal_cents": bundle_savings.get("subtotal_cents"),
        "laptop_subtotal_cents": bundle_savings.get("laptop_subtotal_cents"),
        "accessories_subtotal_cents": bundle_savings.get("accessories_subtotal_cents"),
        "estimated_final_total_cents": bundle_savings.get("estimated_final_total_cents"),
        "items": [
            {
                "sku": it.get("sku"),
                "name": it.get("name"),
                "quantity": it.get("quantity"),
                "price_cents": it.get("price_cents"),
            }
            for it in (items or [])
            if isinstance(it, dict)
        ][:8],
    }
    return enqueue_approval(
        "bundle_discount",
        payload,
        reason="bundle_discount_20pct",
        created_by=created_by,
    )


def bind_bundle_approval_state(
    db,
    *,
    cart_id: str,
    uid: str,
    bundle_savings: Dict[str, Any],
    items: Iterable[Dict[str, Any]],
    created_by: str | None = None,
) -> Dict[str, Any]:
    enriched = dict(bundle_savings or {})
    if not enriched:
        return enriched

    if enriched.get("approval_required") and float(enriched.get("requested_discount_percent") or 0.0) >= 0.2:
        approval_id = ensure_bundle_discount_approval(
            db,
            cart_id=cart_id,
            uid=uid,
            bundle_savings=enriched,
            items=items,
            created_by=created_by,
        )
        if approval_id:
            enriched["approval_id"] = approval_id

    approval = find_bundle_approval(db, cart_id=cart_id)
    if not approval:
        return enriched

    approval_status = str(approval.get("status") or "pending")
    enriched["approval_id"] = approval.get("id")
    enriched["approval_status"] = approval_status

    laptop_subtotal = int(enriched.get("laptop_subtotal_cents") or 0)
    subtotal = int(enriched.get("subtotal_cents") or 0)

    if approval_status == "approved" and float(enriched.get("requested_discount_percent") or 0.0) >= 0.2:
        discount_cents = int(round(laptop_subtotal * 0.20))
        enriched.update(
            {
                "status": "applied",
                "approval_required": False,
                "approval_badge": "20% approved",
                "applied_discount_percent": 0.20,
                "discount_cents": discount_cents,
                "applied_discount_cents": discount_cents,
                "final_total_cents": max(0, subtotal - discount_cents),
                "estimated_final_total_cents": max(0, subtotal - discount_cents),
                "message": "20% bundle discount approved and active on the laptop line item.",
            }
        )
        return enriched

    if approval_status == "rejected" and float(enriched.get("requested_discount_percent") or 0.0) >= 0.2:
        fallback_discount = int(round(laptop_subtotal * 0.15))
        enriched.update(
            {
                "status": "applied",
                "approval_required": False,
                "approval_badge": "20% rejected, 15% active",
                "applied_discount_percent": 0.15,
                "discount_cents": fallback_discount,
                "applied_discount_cents": fallback_discount,
                "final_total_cents": max(0, subtotal - fallback_discount),
                "message": "20% bundle request was rejected. 15% laptop bundle discount remains active.",
            }
        )
        return enriched

    enriched["approval_badge"] = "Pending approval"
    return enriched
