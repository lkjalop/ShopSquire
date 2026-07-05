from __future__ import annotations

import secrets
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from src.app.models.db import db_session
from src.app.routers.auth import _ensure_auth_tables, _user_from_token
from src.app.services.account_purchases import order_tracking, unified_purchases


router = APIRouter(prefix="/api/v1/account", tags=["account"])


class PaymentMethodPayload(BaseModel):
    label: str | None = None
    brand: str | None = None
    last4: str


class ClaimOrderPayload(BaseModel):
    order_id: str
    email: EmailStr


def _require_user(token: str):
    _ensure_auth_tables()
    row = _user_from_token(token)
    if not row:
        raise HTTPException(status_code=401, detail="Invalid token")
    return row


@router.get("/me")
def me(token: str) -> Dict:
    row = _require_user(token)
    return {"user_id": row[0], "email": row[1], "name": row[2]}


@router.get("/orders")
def orders(token: str, limit: int = 20, offset: int = 0) -> Dict:
    row = _require_user(token)
    user_id = row[0]
    limit = max(1, min(int(limit or 20), 50))
    offset = max(0, int(offset or 0))
    with db_session() as db:
        rows = db.execute(
            "SELECT id, total_cents, status, created_at FROM orders WHERE customer_id = :uid ORDER BY created_at DESC LIMIT :limit OFFSET :offset",
            {"uid": user_id, "limit": limit, "offset": offset},
        ).fetchall()
        return {
            "orders": [
                {"order_id": r[0], "total_cents": r[1], "status": r[2], "created_at": str(r[3])}
                for r in rows
            ]
        }


@router.get("/purchases")
def purchases(token: str, limit: int = 20) -> Dict:
    """ONE newest-first timeline of the customer's consumer orders AND procurement/RFQ cases — the
    unified view /orders can't give (it shows consumer orders only). Each entry carries status +
    tracking. This is the customer-facing complement to the internal order→dispatch→ship spine."""
    row = _require_user(token)
    user_id = row[0]
    with db_session() as db:
        items = unified_purchases(db, uid=user_id, customer_id=user_id, limit=limit)
    return {"orders": sum(1 for i in items if i.get("kind") == "order"),
            "procurement_cases": sum(1 for i in items if i.get("kind") == "procurement"),
            "items": items}


@router.get("/orders/{order_id}/tracking")
def order_tracking_view(token: str, order_id: str) -> Dict:
    """Shipment tracking for ONE of the customer's orders (status + tracking number + carrier),
    scoped to the requester — 404 if the order isn't theirs."""
    row = _require_user(token)
    user_id = row[0]
    with db_session() as db:
        rec = order_tracking(db, order_id, uid=user_id, customer_id=user_id)
    if not rec:
        raise HTTPException(status_code=404, detail="order_not_found_for_requester")
    return rec


@router.get("/payment-methods")
def list_methods(token: str) -> Dict:
    row = _require_user(token)
    user_id = row[0]
    with db_session() as db:
        rows = db.execute(
            "SELECT id, label, brand, last4, created_at FROM payment_methods WHERE user_id = :uid ORDER BY created_at DESC",
            {"uid": user_id},
        ).fetchall()
        return {
            "methods": [
                {"id": r[0], "label": r[1], "brand": r[2], "last4": r[3], "created_at": str(r[4])}
                for r in rows
            ]
        }


@router.post("/payment-methods")
def add_method(token: str, payload: PaymentMethodPayload) -> Dict:
    row = _require_user(token)
    user_id = row[0]
    if not payload.last4 or len(payload.last4) < 4:
        raise HTTPException(status_code=400, detail="last4 required")
    pid = secrets.token_hex(8)
    with db_session() as db:
        db.execute(
            "INSERT INTO payment_methods (id, user_id, label, brand, last4) VALUES (:id, :uid, :label, :brand, :last4)",
            {
                "id": pid,
                "uid": user_id,
                "label": payload.label,
                "brand": payload.brand,
                "last4": payload.last4[-4:],
            },
        )
        db.commit()
    return {"created": True, "id": pid}


@router.post("/claim-order")
def claim_order(token: str, payload: ClaimOrderPayload) -> Dict:
    row = _require_user(token)
    user_id = row[0]
    email = payload.email.strip().lower()
    with db_session() as db:
        order = db.execute(
            "SELECT id, customer_id, guest_email, draft_order_id FROM orders WHERE id = :oid",
            {"oid": payload.order_id},
        ).fetchone()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found")
        if order[1]:
            raise HTTPException(status_code=409, detail="Order already claimed")
        guest_email = (order[2] or "").strip().lower()
        if guest_email != email:
            raise HTTPException(status_code=403, detail="Email mismatch")
        db.execute(
            "UPDATE orders SET customer_id = :uid WHERE id = :oid",
            {"uid": user_id, "oid": payload.order_id},
        )
        if order[3]:
            db.execute(
                "UPDATE draft_orders SET customer_id = :uid WHERE id = :did",
                {"uid": user_id, "did": order[3]},
            )
        db.execute(
            "INSERT INTO order_sessions (id, uid, order_id) VALUES (:id, :uid, :oid)",
            {"id": secrets.token_hex(16), "uid": user_id, "oid": payload.order_id},
        )
        db.commit()
    return {"claimed": True, "order_id": payload.order_id}
