from __future__ import annotations

import json
import uuid
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.app.models.db import db_session
from src.app.observability.tracing import get_tracer
from src.app.repositories.catalog import CatalogRepository
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER


router = APIRouter(prefix="/api/v1/cart", tags=["cart"])
tracer = get_tracer("cart-router")


class CartItemIn(BaseModel):
    sku: str
    quantity: int = 1


class CartItemsPayload(BaseModel):
    uid: str
    items: List[CartItemIn]


class CartItemPayload(BaseModel):
    uid: str
    sku: str
    quantity: int = 1


def _load_items(raw) -> List[Dict]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:
            return []
    return []


def _get_or_create_cart(uid: str) -> tuple[str, List[Dict]]:
    with db_session() as db:
        row = db.execute(
            "SELECT id, line_items FROM draft_orders WHERE customer_id = :uid AND status = 'draft' ORDER BY created_at DESC LIMIT 1",
            {"uid": uid},
        ).fetchone()
        if row:
            return row[0], _load_items(row[1])
        cart_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO draft_orders (id, customer_id, line_items, status) VALUES (:id, :uid, :items, 'draft')",
            {"id": cart_id, "uid": uid, "items": json.dumps([])},
        )
        db.commit()
        return cart_id, []


def _save_cart(cart_id: str, items: List[Dict]) -> None:
    with db_session() as db:
        db.execute(
            "UPDATE draft_orders SET line_items = :items, updated_at = CURRENT_TIMESTAMP WHERE id = :id",
            {"items": json.dumps(items), "id": cart_id},
        )
        db.commit()


def _hydrate(items: List[Dict]) -> Dict:
    repo = CatalogRepository()
    out_items = []
    subtotal = 0
    for it in items:
        sku = it.get("sku")
        qty = int(it.get("quantity") or 1)
        if not sku:
            continue
        product = repo.get_product_by_sku(sku)
        if not product:
            out_items.append({"sku": sku, "quantity": qty, "price_cents": 0, "name": "Unknown"})
            continue
        price = int(product.price_cents or 0)
        subtotal += price * qty
        out_items.append(
            {
                "sku": sku,
                "quantity": qty,
                "price_cents": price,
                "name": product.name,
            }
        )
    return {
        "items": out_items,
        "subtotal_cents": subtotal,
        "currency": "USD",
    }


@router.get("")
def get_cart(uid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.get"):
        cart_id, items = _get_or_create_cart(uid)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        return {"cart_id": cart_id, **hydrated}


@router.post("/items")
def add_item(payload: CartItemPayload, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.add_item"):
        if not payload.sku:
            raise HTTPException(status_code=400, detail="SKU required")
        cart_id, items = _get_or_create_cart(payload.uid)
        found = False
        for it in items:
            if it.get("sku") == payload.sku:
                it["quantity"] = int(it.get("quantity") or 1) + int(payload.quantity or 1)
                found = True
                break
        if not found:
            items.append({"sku": payload.sku, "quantity": int(payload.quantity or 1)})
        _save_cart(cart_id, items)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        return {"cart_id": cart_id, **hydrated}


@router.put("/items")
def replace_items(payload: CartItemsPayload, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.replace_items"):
        cart_id, _ = _get_or_create_cart(payload.uid)
        items = [{"sku": it.sku, "quantity": int(it.quantity or 1)} for it in payload.items if it.sku]
        _save_cart(cart_id, items)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        return {"cart_id": cart_id, **hydrated}


@router.delete("/items/{sku}")
def remove_item(sku: str, uid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.remove_item"):
        cart_id, items = _get_or_create_cart(uid)
        items = [it for it in items if it.get("sku") != sku]
        _save_cart(cart_id, items)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        return {"cart_id": cart_id, **hydrated}


@router.post("/clear")
def clear_cart(uid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.clear"):
        cart_id, _ = _get_or_create_cart(uid)
        _save_cart(cart_id, [])
        return {"cart_id": cart_id, "items": [], "subtotal_cents": 0, "currency": "USD"}
