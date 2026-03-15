from __future__ import annotations

import json
import uuid
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.app.models.db import db_session
from src.app.observability.tracing import get_tracer
from src.app.repositories.catalog import CatalogRepository
from src.app.security.commerce_request_guard import inspect_commerce_request
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.services.bundle_approvals import bind_bundle_approval_state
from src.app.services.bundle_pricing import evaluate_bundle_savings
from src.app.services.decision_log import log_trace_event


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
                "specs": product.specs if isinstance(product.specs, dict) else None,
            }
        )
    bundle_savings = evaluate_bundle_savings(out_items)
    return {
        "items": out_items,
        "subtotal_cents": subtotal,
        "currency": "USD",
        "bundle_savings": bundle_savings,
    }


def _cart_trace_id(cart_id: str) -> str:
    return f"cart:{str(cart_id or '').strip()}"


def _log_cart_security_scan(*, trace_id: str, source_id: str, signal: Dict) -> None:
    log_trace_event(
        trace_id=trace_id,
        event_type="security_scan",
        source_type="cart",
        source_id=source_id,
        target_type="cart",
        target_id=trace_id,
        payload={
            "summary": f"{signal.get('surface')}: {signal.get('verdict')}",
            "severity": signal.get("severity"),
            "risk": signal.get("risk"),
            "mitre_atlas": signal.get("mitre_atlas") or [],
            "mitre_attack": signal.get("mitre_attack") or [],
            "signals": signal.get("reasons") or [],
            "mitigations": signal.get("mitigations") or [],
            "surface": signal.get("surface"),
            "verdict": signal.get("verdict"),
        },
    )


def _guard_cart_request(*, surface: str, uid: str, sku_values: List[str], quantity_values: List[int]) -> Dict:
    signal = inspect_commerce_request(
        surface=surface,
        texts=[uid, sku_values],
        sku_values=sku_values,
        uid=uid,
        quantity_values=quantity_values,
    )
    if signal.get("verdict") == "block":
        guard_trace_id = f"cart-guard:{uuid.uuid4()}"
        _log_cart_security_scan(trace_id=guard_trace_id, source_id=surface, signal=signal)
        raise HTTPException(
            status_code=400,
            detail=f"blocked_{surface}: {', '.join(signal.get('reasons') or ['invalid_payload'])}; trace_id={guard_trace_id}",
        )
    return signal


def _with_bundle_state(*, cart_id: str, uid: str, role: str, hydrated: Dict) -> Dict:
    with db_session() as db:
        hydrated["bundle_savings"] = bind_bundle_approval_state(
            db,
            cart_id=cart_id,
            uid=uid,
            bundle_savings=hydrated.get("bundle_savings") or {},
            items=hydrated.get("items") or [],
            created_by=role,
        )
    hydrated["trace_id"] = _cart_trace_id(cart_id)
    hydrated["decision_trace_id"] = hydrated["trace_id"]
    return hydrated


@router.get("")
def get_cart(uid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.get"):
        signal = _guard_cart_request(surface="cart.get", uid=uid, sku_values=[], quantity_values=[])
        cart_id, items = _get_or_create_cart(uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.get", signal=signal)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        hydrated = _with_bundle_state(cart_id=cart_id, uid=uid, role=role, hydrated=hydrated)
        return {"cart_id": cart_id, **hydrated}


@router.post("/items")
def add_item(payload: CartItemPayload, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.add_item"):
        if not payload.sku:
            raise HTTPException(status_code=400, detail="SKU required")
        signal = _guard_cart_request(
            surface="cart.add_item",
            uid=payload.uid,
            sku_values=[payload.sku],
            quantity_values=[payload.quantity],
        )
        cart_id, items = _get_or_create_cart(payload.uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.add_item", signal=signal)
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
        hydrated = _with_bundle_state(cart_id=cart_id, uid=payload.uid, role=role, hydrated=hydrated)
        return {"cart_id": cart_id, **hydrated}


@router.put("/items")
def replace_items(payload: CartItemsPayload, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.replace_items"):
        signal = _guard_cart_request(
            surface="cart.replace_items",
            uid=payload.uid,
            sku_values=[str(it.sku or "") for it in payload.items],
            quantity_values=[int(it.quantity or 1) for it in payload.items],
        )
        cart_id, _ = _get_or_create_cart(payload.uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.replace_items", signal=signal)
        items = [{"sku": it.sku, "quantity": int(it.quantity or 1)} for it in payload.items if it.sku]
        _save_cart(cart_id, items)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        hydrated = _with_bundle_state(cart_id=cart_id, uid=payload.uid, role=role, hydrated=hydrated)
        return {"cart_id": cart_id, **hydrated}


@router.delete("/items/{sku}")
def remove_item(sku: str, uid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.remove_item"):
        signal = _guard_cart_request(surface="cart.remove_item", uid=uid, sku_values=[sku], quantity_values=[1])
        cart_id, items = _get_or_create_cart(uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.remove_item", signal=signal)
        items = [it for it in items if it.get("sku") != sku]
        _save_cart(cart_id, items)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        hydrated = _with_bundle_state(cart_id=cart_id, uid=uid, role=role, hydrated=hydrated)
        return {"cart_id": cart_id, **hydrated}


@router.post("/clear")
def clear_cart(uid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.clear"):
        signal = _guard_cart_request(surface="cart.clear", uid=uid, sku_values=[], quantity_values=[])
        cart_id, _ = _get_or_create_cart(uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.clear", signal=signal)
        _save_cart(cart_id, [])
        return {
            "cart_id": cart_id,
            "items": [],
            "subtotal_cents": 0,
            "currency": "USD",
            "trace_id": _cart_trace_id(cart_id),
            "decision_trace_id": _cart_trace_id(cart_id),
        }
