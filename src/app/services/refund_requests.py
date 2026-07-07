"""Governed refund REQUEST creation — the shared core of the GATE-2 refund rail.

Extracted from routers/payments.py::refund_request so the returns/claims pipeline can open a refund
request PROGRAMMATICALLY on the same governed rail the merchant HTTP endpoint uses (previously the claim
pipeline decided "auto_approve" and then… nothing — the two systems were disconnected).

Invariants preserved exactly:
  - request only against a paid/shipped/delivered order;
  - one open request per order;
  - amount within the remaining refundable balance;
  - approval remains a SEPARATE human-owner step (POST /refunds/{order_id}/approve) — nothing here moves money.

Returns {"ok": bool, ...} instead of raising, so a programmatic caller (returns.submit) can downgrade its
decision on failure; the HTTP router maps the error strings back to its original status codes.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import text


def create_refund_request(
    db,
    *,
    order_id: str,
    amount_cents: Optional[int] = None,
    reason: str = "",
    actor_type: str = "role",
    actor_id: str = "system",
    clamp: bool = False,
) -> Dict[str, Any]:
    """Open a refund request on the governed ledger. amount_cents=None → full remaining refundable.

    clamp=True (programmatic callers): an amount above the refundable balance is clamped down instead of
    rejected — the claim's asserted value may legitimately exceed what is still refundable. The HTTP path
    keeps clamp=False (strict 422) so merchant input errors stay loud.
    """
    from src.app.services.payment_ledger import KIND_REFUND_REQUESTED, record_txn, refund_state

    row = db.execute(
        text("SELECT status, total_cents, currency FROM orders WHERE id = :o LIMIT 1"),
        {"o": order_id},
    ).fetchone()
    if not row:
        return {"ok": False, "error": "order_not_found", "order_id": order_id}
    order_status = str(row[0])
    if order_status not in ("paid", "shipped", "delivered"):
        return {"ok": False, "error": "order_not_refundable", "order_id": order_id, "order_status": order_status}

    state = refund_state(db, order_id)
    if state["open_request"]:
        return {"ok": False, "error": "refund_request_already_open", "order_id": order_id}

    refundable = int(state["captured_cents"] or row[1] or 0) - int(state["settled_cents"] or 0)
    amount = int(amount_cents) if amount_cents is not None else refundable
    if clamp and amount > refundable:
        amount = refundable
    if amount <= 0 or amount > refundable:
        return {"ok": False, "error": "invalid_refund_amount", "order_id": order_id,
                "refundable_cents": refundable}

    record_txn(db, order_id=order_id, kind=KIND_REFUND_REQUESTED, amount_cents=amount,
               currency=str(row[2] or "USD"), actor_type=actor_type, actor_id=actor_id,
               reason=reason, commit=True)
    return {"ok": True, "order_id": order_id, "status": "refund_requested", "amount_cents": amount,
            "approval_required": True,
            "approve_via": f"/api/v1/payments/refunds/{order_id}/approve"}
