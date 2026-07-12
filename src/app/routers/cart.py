from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.app.models.db import db_session
from src.app.observability.tracing import get_tracer
from src.app.repositories.catalog import CatalogRepository
from src.app.security.commerce_request_guard import inspect_commerce_request
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.deps import get_redis
from src.app.services.bundle_approvals import bind_bundle_approval_state
from src.app.services.bundle_pricing import evaluate_bundle_savings
from src.app.services.cart_ttl import classify_updated_at
from src.app.services.decision_log import log_trace_event


router = APIRouter(prefix="/api/v1/cart", tags=["cart"])
tracer = get_tracer("cart-router")
_vlog = logging.getLogger("shopsquire.cart.voucher")


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
    # Procurement-aware amendment (multi-intent "actually 15 instead"): allow the line qty to EXCEED
    # on-hand stock instead of a 409 — the shortfall is sourced from suppliers at cart-confirmation (GATE 1).
    # Default False keeps the normal retail stock gate intact for the ordinary stepper / add path.
    allow_sourcing: bool = False


# Per-line quantity ceiling (matches scatter_gather_guard's 1..500 sanity). Bounds the allow_sourcing path
# so lifting the STOCK gate can't push an unbounded qty into the cart from a single request.
_MAX_LINE_QTY = 500


def apply_quantity_line(items: List[Dict], sku: str, target: int, stock: int,
                        allow_sourcing: bool) -> tuple[List[Dict], Optional[Dict], Optional[Dict]]:
    """THE per-line quantity decision (C1): the PUT handler and the transactional mutation
    service both call this — one decision surface, never two copies that drift. Pure over its
    inputs. Returns (new_items, shortfall_meta, error): error is the handler's exact detail
    shape (quantity_out_of_range / out_of_stock / insufficient_stock) or None on success."""
    if target > _MAX_LINE_QTY:
        return items, None, {"error": "quantity_out_of_range", "sku": sku,
                             "requested": target, "max": _MAX_LINE_QTY}
    shortfall_meta: Optional[Dict] = None
    if target > 0 and stock < target:
        if not allow_sourcing:
            return items, None, {"error": "out_of_stock" if stock == 0 else "insufficient_stock",
                                 "sku": sku, "available": stock, "requested": target}
        shortfall_meta = {"available_now": int(stock), "shortfall": int(target - stock),
                          "requested": int(target)}
    if target <= 0:
        return [it for it in items if it.get("sku") != sku], None, None
    out = list(items)
    found = False
    for it in out:
        if it.get("sku") == sku:
            it["quantity"] = target
            it["sourcing_required"] = bool(shortfall_meta)
            if shortfall_meta:
                it["shortfall"] = shortfall_meta["shortfall"]
                it["available_now"] = shortfall_meta["available_now"]
            else:
                it.pop("shortfall", None); it.pop("available_now", None)
            found = True
            break
    if not found:
        line: Dict[str, Any] = {"sku": sku, "quantity": target,
                                "sourcing_required": bool(shortfall_meta), "added_at": _now_ts()}
        if shortfall_meta:
            line["shortfall"] = shortfall_meta["shortfall"]
            line["available_now"] = shortfall_meta["available_now"]
        out.append(line)
    return out, shortfall_meta, None


def _now_ts() -> str:
    """UTC 'YYYY-MM-DD HH:MM:SS' — same format as draft_orders.updated_at, so per-line added_at and the
    cart's updated_at compare cleanly (see services/cart_ttl.py)."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


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


def _get_or_create_cart(uid: str) -> tuple[str, List[Dict], Optional[str]]:
    """Returns (cart_id, items, updated_at). updated_at is the last-touched timestamp used for cart-age
    labelling; None for a brand-new empty cart (no meaningful age to report yet)."""
    with db_session() as db:
        row = db.execute(
            "SELECT id, line_items, updated_at FROM draft_orders WHERE customer_id = :uid AND status = 'draft' ORDER BY created_at DESC LIMIT 1",
            {"uid": uid},
        ).fetchone()
        if row:
            return row[0], _load_items(row[1]), row[2]
        cart_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO draft_orders (id, customer_id, line_items, status) VALUES (:id, :uid, :items, 'draft')",
            {"id": cart_id, "uid": uid, "items": json.dumps([])},
        )
        db.commit()
        return cart_id, [], None


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
            # an unresolvable SKU (deleted/renamed product) can never be ordered — skip it rather than
            # surface a phantom "Unknown / $0" row that clutters the cart (demo-cart-hygiene fix).
            continue
        price = int(product.price_cents or 0)
        subtotal += price * qty
        row = {
            "sku": sku,
            "quantity": qty,
            "price_cents": price,
            "name": product.name,
            "specs": product.specs if isinstance(product.specs, dict) else None,
        }
        # Per-line age: when this line was first added. Lets the UI resolve "the latest unit" exactly
        # (most-recent added_at) instead of guessing from array order, and feeds future per-line TTL.
        if it.get("added_at"):
            row["added_at"] = it.get("added_at")
        # Carry the procurement-shortfall markers through so the "X will be sourced" state is DURABLE
        # across GET /cart (not just the one PUT echo) — the UI reads them to badge the line.
        if it.get("sourcing_required"):
            row["sourcing_required"] = True
            row["shortfall"] = int(it.get("shortfall") or 0)
            row["available_now"] = int(it.get("available_now") or 0)
        out_items.append(row)
    bundle_savings = evaluate_bundle_savings(out_items)
    return {
        "items": out_items,
        "subtotal_cents": subtotal,
        "currency": "USD",
        "bundle_savings": bundle_savings,
    }


def _cart_trace_id(cart_id: str) -> str:
    return f"cart:{str(cart_id or '').strip()}"


# ── Reload-durable UNDO: a cleared cart is stashed in Redis so "put them back" survives a page reload.
# This is a SEPARATE snapshot (not a tombstone inside line_items), so it never touches the cart read paths.
def _undo_key(uid: str) -> str:
    return f"session:{str(uid or '').strip()}:cart_undo"


def _undo_ttl() -> int:
    """Grace window (seconds) for restoring a cleared cart. Default 1h; override via CART_UNDO_TTL_SECONDS."""
    try:
        return max(60, min(86400, int(float(os.getenv("CART_UNDO_TTL_SECONDS", "3600") or 3600))))
    except (TypeError, ValueError):
        return 3600


def _undo_available(redis, uid: str) -> Dict[str, Any]:
    """Is there a restorable snapshot for this uid? Returns {available, count} (best-effort; never raises)."""
    try:
        raw = redis.get(_undo_key(uid)) if redis is not None else None
    except Exception:
        raw = None
    if not raw:
        return {"available": False, "count": 0}
    try:
        snap = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        return {"available": True, "count": len(snap.get("items") or [])}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {"available": False, "count": 0}


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
def get_cart(uid: str, redis=Depends(get_redis),
            role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.get"):
        signal = _guard_cart_request(surface="cart.get", uid=uid, sku_values=[], quantity_values=[])
        cart_id, items, updated_at = _get_or_create_cart(uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.get", signal=signal)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        hydrated = _with_bundle_state(cart_id=cart_id, uid=uid, role=role, hydrated=hydrated)
        # Cart age (truth, not a frontend guess): idle delta since last touch -> tier + human label the UI
        # trusts for the "carried over" nudge. Only meaningful when the cart has items.
        hydrated["updated_at"] = updated_at
        hydrated["age"] = classify_updated_at(updated_at) if (hydrated.get("items")) else classify_updated_at(None)
        # Reload-durable undo: expose whether a just-cleared cart can still be restored, so the Undo
        # affordance survives a page reload (the local chip lives only in React state).
        hydrated["undo"] = _undo_available(redis, uid)
        return {"cart_id": cart_id, **hydrated}


class UndoStashPayload(BaseModel):
    uid: str
    items: List[CartItemIn]


@router.post("/undo/stash")
def stash_cart_undo(payload: UndoStashPayload, redis=Depends(get_redis),
                    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Persist the lines a client-side clear just removed, so 'undo' survives a reload. Best-effort — a
    Redis hiccup degrades to the in-session chip, never blocks the clear."""
    _guard_cart_request(surface="cart.undo_stash", uid=payload.uid, sku_values=[], quantity_values=[])
    lines = [{"sku": str(it.sku), "quantity": max(1, int(it.quantity or 1))} for it in payload.items if it.sku]
    if not lines:
        return {"stashed": False, "count": 0}
    try:
        redis.setex(_undo_key(payload.uid), _undo_ttl(), json.dumps({"items": lines, "saved_at": _now_ts()}))
    except Exception:
        return {"stashed": False, "count": 0}
    return {"stashed": True, "count": len(lines), "ttl_seconds": _undo_ttl()}


@router.post("/undo")
def undo_cart_clear(uid: str, redis=Depends(get_redis),
                    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Restore the most-recently cleared cart from its Redis snapshot (within the grace window). Merges the
    stashed lines back into the current cart and consumes the snapshot. 404 if nothing is restorable."""
    _guard_cart_request(surface="cart.undo", uid=uid, sku_values=[], quantity_values=[])
    key = _undo_key(uid)
    try:
        raw = redis.get(key)
    except Exception:
        raw = None
    if not raw:
        raise HTTPException(status_code=404, detail="no_undo_available")
    try:
        snap = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    except (json.JSONDecodeError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="no_undo_available")

    cart_id, items, _ = _get_or_create_cart(uid)
    by_sku = {it.get("sku"): it for it in items}
    ts = _now_ts()
    restored = 0
    for line in (snap.get("items") or []):
        sku = line.get("sku")
        qty = max(1, int(line.get("quantity") or 1))
        if not sku:
            continue
        # Restore = re-instate exactly what was cleared, bypassing the stock gate (the removal freed the
        # stock, and this is the buyer's own cart being put back — any true shortfall is caught at checkout).
        if sku in by_sku:
            by_sku[sku]["quantity"] = int(by_sku[sku].get("quantity") or 0) + qty
        else:
            new_line = {"sku": sku, "quantity": qty, "added_at": ts}
            items.append(new_line)
            by_sku[sku] = new_line
        restored += 1
    _save_cart(cart_id, items)
    try:
        redis.delete(key)
    except Exception:
        pass
    hydrated = _hydrate(items)
    hydrated = _with_bundle_state(cart_id=cart_id, uid=uid, role=role, hydrated=hydrated)
    hydrated["undo"] = {"available": False, "count": 0}
    return {"cart_id": cart_id, "restored": restored, **hydrated}


@router.get("/split-offer")
def split_offer(uid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Split-fulfillment offer for the buyer's cart, surfaced BEFORE payment: what ships NOW (from on-hand
    stock) vs what FOLLOWS from a supplier — the "follows" ETA is the SUPPLIER's own lead time (a real figure
    from the supplier catalog, not a guess). Delivery fees + the free-shipping threshold come from the active
    StoreProfile (agnostic — every store sets its own economics). The buyer CONFIRMS this before payment; we
    never silently split a shipment or add a fee. A fully-in-stock cart returns a single-shipment plan."""
    from src.app.services.fulfillment.fulfillment_split import (
        SplitLine, compute_split, delivery_policy_from_profile)
    from src.app.services.supplier_catalog import lead_times_for_skus

    with tracer.start_as_current_span("cart.split_offer"):
        cart_id, items, _ = _get_or_create_cart(uid)
        hydrated = _hydrate(items)
        rows = hydrated.get("items") or []
        if not rows:
            return {"cart_id": cart_id, "subtotal_cents": 0, "currency": "USD", "split": None}
        skus = [str(r["sku"]) for r in rows if r.get("sku")]
        stock = _batch_stock_levels(skus)
        try:
            with db_session() as db:
                leads = lead_times_for_skus(db, skus)
        except Exception:
            leads = {}
        lines = [
            SplitLine(
                sku=str(r.get("sku")),
                requested_qty=int(r.get("quantity") or 1),
                in_stock=int(stock.get(str(r.get("sku")), 0)),
                unit_cents=int(r.get("price_cents") or 0),
                supplier_lead_time_days=(leads.get(str(r.get("sku"))) or {}).get("lead_time_days"),
                supplier_ref=(leads.get(str(r.get("sku"))) or {}).get("supplier_ref"),
            )
            for r in rows if r.get("sku")
        ]
        plan = compute_split(lines, policy=delivery_policy_from_profile())
        # supplier directory for the UI (name + reorder channel per referenced supplier) — the Procurement
        # tab's PENDING-plan view groups the backorder by supplier and shows HOW each would be reached.
        suppliers: Dict[str, Dict] = {}
        for meta in leads.values():
            ref = meta.get("supplier_ref")
            if ref and ref not in suppliers:
                suppliers[ref] = {"name": meta.get("supplier_name"), "channel": meta.get("channel")}
        return {"cart_id": cart_id, "subtotal_cents": int(hydrated.get("subtotal_cents", 0) or 0),
                "currency": hydrated.get("currency", "USD"), "split": plan.as_dict(),
                "suppliers": suppliers}


def _get_cart_sku_qty(uid: str, sku: str) -> int:
    """Return quantity of *sku* already in uid's active cart without creating one."""
    try:
        from sqlalchemy import text as _text
        with db_session() as db:
            row = db.execute(
                _text(
                    "SELECT line_items FROM draft_orders "
                    "WHERE customer_id = :uid AND status = 'draft' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"uid": str(uid)},
            ).fetchone()
        if not row:
            return 0
        items = _load_items(row[0])
        return next((int(it.get("quantity") or 0) for it in items if it.get("sku") == sku), 0)
    except Exception:
        return 0


def _get_stock_level(sku: str) -> int:
    """Return current stock for *sku* joining through products (inventory has no sku column)."""
    try:
        from sqlalchemy import text as _text
        with db_session() as db:
            row = db.execute(
                _text(
                    "SELECT COALESCE(SUM(i.stock), 0) "
                    "FROM inventory i "
                    "JOIN products p ON p.id = i.product_id "
                    "WHERE p.sku = :sku"
                ),
                {"sku": str(sku)},
            ).fetchone()
            return int(row[0] or 0) if row else 0
    except Exception:
        return 0


def _batch_stock_levels(skus: List[str]) -> Dict[str, int]:
    """Batch variant of _get_stock_level for the PUT stock gate."""
    if not skus:
        return {}
    try:
        from sqlalchemy import text as _text
        params = {f"s{i}": s for i, s in enumerate(skus)}
        placeholders = ", ".join(f":{k}" for k in params)
        with db_session() as db:
            rows = db.execute(
                _text(
                    f"SELECT p.sku, COALESCE(SUM(i.stock), 0) "
                    f"FROM products p "
                    f"LEFT JOIN inventory i ON i.product_id = p.id "
                    f"WHERE p.sku IN ({placeholders}) "
                    f"GROUP BY p.sku"
                ),
                params,
            ).fetchall()
        result = {str(r[0]): int(r[1] or 0) for r in rows}
        for sku in skus:
            result.setdefault(sku, 0)
        return result
    except Exception:
        return {sku: 0 for sku in skus}


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
        # Stock gate: validate before touching the cart so rejected requests
        # never create phantom carts. Read existing qty with a lightweight
        # read-only query (no cart creation), then stock check, then get-or-create.
        requested_qty = int(payload.quantity or 1)
        existing_qty = _get_cart_sku_qty(payload.uid, payload.sku)
        total_qty = existing_qty + requested_qty
        stock = _get_stock_level(payload.sku)
        if stock == 0:
            raise HTTPException(
                status_code=409,
                detail={"error": "out_of_stock", "sku": payload.sku, "available": 0},
            )
        if stock < total_qty:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "insufficient_stock",
                    "sku": payload.sku,
                    "available": stock,
                    "in_cart": existing_qty,
                    "requested": requested_qty,
                    "total_would_be": total_qty,
                },
            )
        # Stock validated — now get-or-create the cart and persist.
        cart_id, items, _ = _get_or_create_cart(payload.uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.add_item", signal=signal)
        found = False
        for it in items:
            if it.get("sku") == payload.sku:
                it["quantity"] = total_qty
                found = True
                break
        if not found:
            items.append({"sku": payload.sku, "quantity": requested_qty, "added_at": _now_ts()})
        _save_cart(cart_id, items)
        # S3 human-correction learning: adding a SKU to cart is an acceptance signal for that product
        # (gated by HUMAN_FEEDBACK_CAPTURE_ENABLED; inert + best-effort by default).
        try:
            from src.app.models.db import db_session as _hf_db
            from src.app.services.human_feedback import capture_feedback
            with _hf_db() as _hfdb:
                capture_feedback(_hfdb, "recommendation_accepted", subject_hash=str(payload.uid),
                                 entity_ref=str(payload.sku), source="cart.add_item",
                                 dedup_fields={"uid": str(payload.uid), "sku": str(payload.sku)})
        except Exception:
            pass
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        hydrated = _with_bundle_state(cart_id=cart_id, uid=payload.uid, role=role, hydrated=hydrated)
        # ── Upsell candidates ──────────────────────────────────────────────────
        try:
            from src.app.services.upsell_engine import get_upsell_candidates
            cart_skus = [it.get("sku") for it in items if it.get("sku") and it.get("sku") != payload.sku]
            # Retrieve session query from Redis for NLP use-case expansion (best-effort)
            session_query = None
            try:
                from src.app.deps import get_redis
                _r = get_redis()
                _q_raw = _r.get(f"session:{payload.uid}:last_query")
                if _q_raw:
                    session_query = _q_raw.decode("utf-8") if isinstance(_q_raw, bytes) else str(_q_raw)
            except Exception:
                pass
            upsell = get_upsell_candidates(
                added_sku=payload.sku,
                cart_skus=cart_skus,
                session_query=session_query,
                max_results=3,
            )
            if upsell:
                hydrated["upsell"] = {"trigger": "cart_add", "candidates": upsell}
        except Exception:
            pass  # Upsell failure is non-fatal
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
        # Aggregate duplicate SKUs in the payload before checking stock.
        aggregated: Dict[str, int] = {}
        for it in payload.items:
            if not it.sku:
                continue
            aggregated[str(it.sku)] = aggregated.get(str(it.sku), 0) + int(it.quantity or 1)

        # Batch stock check: reject any SKU whose requested qty exceeds available stock.
        if aggregated:
            stock_map = _batch_stock_levels(list(aggregated.keys()))
            oos_errors = []
            over_errors = []
            for sku, qty in aggregated.items():
                avail = stock_map.get(sku, 0)
                if avail == 0:
                    oos_errors.append({"sku": sku, "available": 0})
                elif avail < qty:
                    over_errors.append({"sku": sku, "available": avail, "requested": qty})
            if oos_errors or over_errors:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "stock_validation_failed",
                        "out_of_stock": oos_errors,
                        "insufficient_stock": over_errors,
                    },
                )

        cart_id, _, _ = _get_or_create_cart(payload.uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.replace_items", signal=signal)
        # Use aggregated quantities (deduped) as the canonical line items.
        _ts = _now_ts()
        items = [{"sku": sku, "quantity": qty, "added_at": _ts} for sku, qty in aggregated.items()]
        _save_cart(cart_id, items)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        hydrated = _with_bundle_state(cart_id=cart_id, uid=payload.uid, role=role, hydrated=hydrated)
        return {"cart_id": cart_id, **hydrated}


@router.delete("/items/{sku}")
def remove_item(sku: str, uid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.remove_item"):
        signal = _guard_cart_request(surface="cart.remove_item", uid=uid, sku_values=[sku], quantity_values=[1])
        cart_id, items, _ = _get_or_create_cart(uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.remove_item", signal=signal)
        items = [it for it in items if it.get("sku") != sku]
        _save_cart(cart_id, items)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        hydrated = _with_bundle_state(cart_id=cart_id, uid=uid, role=role, hydrated=hydrated)
        return {"cart_id": cart_id, **hydrated}


@router.put("/items/{sku}")
def set_item_quantity(sku: str, payload: CartItemPayload,
                      role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """SET a line's ABSOLUTE quantity (the cart stepper / 'change your mind' control) — distinct from
    POST /items which INCREMENTS. qty<=0 removes the line. Stock-gated like add. Vertical-blind."""
    with tracer.start_as_current_span("cart.set_item_quantity"):
        target = int(payload.quantity or 0)
        signal = _guard_cart_request(surface="cart.set_item_quantity", uid=payload.uid,
                                     sku_values=[sku], quantity_values=[max(0, target)])
        # THE per-line decision lives in apply_quantity_line (shared with the C1 transactional
        # mutation service — one decision surface). The handler translates its error dicts to
        # the same HTTP statuses as before: 400 out-of-range, 409 stock. Validated BEFORE
        # get-or-create so a rejected request never creates a phantom cart (its error paths
        # are item-independent).
        stock = _get_stock_level(sku) if target > 0 else 0
        _, _, err = apply_quantity_line([], sku, target, stock, bool(payload.allow_sourcing))
        if err is not None:
            raise HTTPException(status_code=400 if err["error"] == "quantity_out_of_range" else 409,
                                detail=err)
        cart_id, items, _ = _get_or_create_cart(payload.uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.set_item_quantity", signal=signal)
        items, shortfall_meta, _err2 = apply_quantity_line(
            items, sku, target, stock, bool(payload.allow_sourcing))
        _save_cart(cart_id, items)
        with tracer.start_as_current_span("cart.hydrate"):
            hydrated = _hydrate(items)
        hydrated = _with_bundle_state(cart_id=cart_id, uid=payload.uid, role=role, hydrated=hydrated)
        out = {"cart_id": cart_id, **hydrated}
        if shortfall_meta:
            out["sourcing_required"] = True
            out["sourcing_shortfall"] = {"sku": sku, **shortfall_meta}
        return out


@router.post("/clear")
def clear_cart(uid: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    with tracer.start_as_current_span("cart.clear"):
        signal = _guard_cart_request(surface="cart.clear", uid=uid, sku_values=[], quantity_values=[])
        cart_id, _, _ = _get_or_create_cart(uid)
        _log_cart_security_scan(trace_id=_cart_trace_id(cart_id), source_id="cart.clear", signal=signal)
        _save_cart(cart_id, [])
        # A cleared cart is a NEW shopping intent — yesterday's approved bundle discount must not ride
        # along onto whatever the buyer builds next (the stale "-$17,627 discount I didn't select" bug).
        try:
            from src.app.services.bundle_approvals import expire_bundle_approvals_for_cart
            with db_session() as _bdb:
                expire_bundle_approvals_for_cart(_bdb, cart_id=cart_id)
        except Exception as _bexp:
            logging.getLogger("shopsquire.cart").debug("bundle-approval expiry on clear failed: %s", _bexp)
        return {
            "cart_id": cart_id,
            "items": [],
            "subtotal_cents": 0,
            "currency": "USD",
            "trace_id": _cart_trace_id(cart_id),
            "decision_trace_id": _cart_trace_id(cart_id),
        }


# ── Programmatic cart mutation (V2 cart milestone) ──────────────────────────────
# The chat/recommend path resolves a natural-language cart edit into a typed, SKU-bound plan
# (recommendation_core.cart_resolver). This applies that plan by REUSING the same guarded,
# stock-gated route handlers the REST API uses — never a second copy of the stock/sourcing gate
# (the duplicated-decision-surface class). Ops apply sequentially over the lock-free
# read-modify-write cart, the frontend's proven pattern (parallel deletes race and drop a line).
def apply_cart_ops(uid: str, ops, *, role: str, allow_sourcing: bool = False,
                   carried_skus: Optional[List[str]] = None) -> Dict[str, Any]:
    """Execute a resolved cart plan. `ops` are duck-typed (.action / .target_skus / .quantity) so
    this stays decoupled from the resolver's dataclass (no core→router import). Returns
    {applied, rejected, cart}; a stock-gated set_quantity that the handler rejects lands in
    `rejected` with the handler's own error, never a silent drop. Never raises for a per-op
    failure — the buyer gets an honest partial result."""
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    carried = {str(s) for s in (carried_skus or [])}

    def _remove(sku: str) -> None:
        remove_item(sku=sku, uid=uid, role=role)
        applied.append({"action": "remove_items", "sku": sku})

    for op in (ops or []):
        action = str(getattr(op, "action", "") or "")
        targets = list(getattr(op, "target_skus", ()) or ())
        try:
            if action == "clear_all":
                clear_cart(uid=uid, role=role)
                applied.append({"action": "clear_all"})
            elif action == "clear_previous":
                # 'previous session' is caller-supplied context (the session-start snapshot lives
                # in the frontend today). Without it we cannot safely decide which lines are
                # carried, so we record it unresolved rather than guess-and-wipe.
                if carried:
                    _, items, _ = _get_or_create_cart(uid)
                    for it in items:
                        s = it.get("sku")
                        if s and str(s) in carried:
                            _remove(str(s))
                else:
                    rejected.append({"action": "clear_previous", "error": "no_carried_set"})
            elif action == "remove_items":
                for sku in targets:
                    _remove(str(sku))
            elif action == "keep_only":
                keep = {str(s) for s in targets}
                _, items, _ = _get_or_create_cart(uid)
                for it in items:
                    s = it.get("sku")
                    if s and str(s) not in keep:
                        _remove(str(s))
            elif action == "set_quantity":
                if not targets:
                    continue
                sku = str(targets[0])
                qty = int(getattr(op, "quantity", 0) or 0)
                payload = CartItemPayload(uid=uid, sku=sku, quantity=qty, allow_sourcing=allow_sourcing)
                try:
                    result = set_item_quantity(sku=sku, payload=payload, role=role)
                    entry = {"action": "set_quantity", "sku": sku, "quantity": qty}
                    if result.get("sourcing_required"):
                        entry["sourcing"] = result.get("sourcing_shortfall")
                    applied.append(entry)
                except HTTPException as he:
                    rejected.append({"action": "set_quantity", "sku": sku, "quantity": qty,
                                     "error": he.detail})
        except HTTPException as he:
            rejected.append({"action": action, "error": he.detail})

    _, items, _ = _get_or_create_cart(uid)
    return {"applied": applied, "rejected": rejected, "cart": _hydrate(items)}


# ── Voucher / Discount Code ────────────────────────────────────────────────────

_VOUCHER_ENABLED = os.getenv("VOUCHER_ENDPOINT_ENABLED", "0").strip().lower() in ("1", "true", "yes")


def _ensure_voucher_tables() -> None:
    """Create vouchers and cart_vouchers tables if they don't exist.

    Safe to call multiple times (CREATE TABLE IF NOT EXISTS).
    Called lazily on first voucher request to avoid blocking startup.
    """
    from sqlalchemy import text as _text
    with db_session() as db:
        db.execute(_text("""
            CREATE TABLE IF NOT EXISTS vouchers (
                id          TEXT PRIMARY KEY,
                code        TEXT NOT NULL UNIQUE,
                discount_cents  INTEGER DEFAULT 0,
                discount_pct    REAL DEFAULT 0.0,
                description TEXT,
                max_uses    INTEGER,
                use_count   INTEGER DEFAULT 0,
                active      INTEGER DEFAULT 1,
                min_order_cents INTEGER DEFAULT 0,
                applies_to_skus TEXT,
                expires_at  TEXT
            )
        """))
        db.execute(_text("""
            CREATE TABLE IF NOT EXISTS cart_vouchers (
                id          TEXT PRIMARY KEY,
                cart_id     TEXT NOT NULL,
                voucher_id  TEXT NOT NULL,
                applied_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                voided_at   TEXT,
                UNIQUE (cart_id, voucher_id)
            )
        """))
        try:
            db.commit()
        except Exception:
            pass


class VoucherPayload(BaseModel):
    uid: str
    code: str


def _parse_applies_to_skus(raw) -> set[str]:
    """Parse the vouchers.applies_to_skus TEXT column into an uppercased SKU set.

    Accepts a JSON array (["SKU-1","SKU-2"]) or a comma/space-separated list. An empty/None
    value means 'no restriction' → empty set (caller treats empty as 'applies to all')."""
    if not raw:
        return set()
    s = str(raw).strip()
    if not s:
        return set()
    parsed = None
    if s.startswith("["):
        try:
            import json as _json
            parsed = _json.loads(s)
        except Exception:
            parsed = None
    if parsed is None:
        parsed = re.split(r"[,\s]+", s)
    return {str(x).strip().upper() for x in parsed if str(x).strip()}


def _voucher_eligibility_error(
    min_order_cents,
    applies_to_skus_raw,
    cart_subtotal_cents: int,
    cart_skus: list[str] | None,
) -> str | None:
    """Pure eligibility gate (B1/B2). Returns an error detail string if the cart is NOT
    eligible for the voucher, else None. Enforces min_order_cents and applies_to_skus —
    both were previously read from the row but never checked."""
    if min_order_cents and int(min_order_cents) > 0 and int(cart_subtotal_cents or 0) < int(min_order_cents):
        return "voucher_min_order_not_met"
    allowed_skus = _parse_applies_to_skus(applies_to_skus_raw)
    if allowed_skus:
        cart_sku_set = {str(s).strip().upper() for s in (cart_skus or []) if s}
        if not (cart_sku_set & allowed_skus):
            return "voucher_not_applicable_to_cart"
    return None


def _apply_voucher_atomic(
    cart_id: str,
    uid: str,
    code: str,
    cart_subtotal_cents: int = 0,
    cart_skus: list[str] | None = None,
) -> Dict:
    """Apply a voucher code to a cart using Redis SETNX for distributed locking.

    Protects against:
    - Race conditions: two simultaneous requests with the same code
    - Replay attacks: cancel+reuse by marking used atomically with DB update
    - Stacking: enforces one active voucher per cart
    - Eligibility (B1/B2): enforces min_order_cents and applies_to_skus BEFORE binding,
      so a voucher cannot be redeemed below its minimum order or against the wrong SKUs.

    Returns a dict with keys: discount_cents, discount_pct, description, voucher_id.
    Raises HTTPException on any invalid/already-used/OOS/ineligible state.
    """
    from sqlalchemy import text as _text

    # ── Sanitise code ──────────────────────────────────────────────────────────
    code = str(code or "").strip().upper()
    if not code or len(code) > 64:
        raise HTTPException(status_code=400, detail="invalid_voucher_code")

    # ── Redis distributed lock (SETNX, 30s TTL) ───────────────────────────────
    redis_client = None
    lock_key = f"voucher:lock:{code}"
    lock_acquired = False
    try:
        from src.app.deps import get_redis
        redis_client = get_redis()
        lock_acquired = bool(redis_client.set(lock_key, cart_id, nx=True, ex=30))
        if not lock_acquired:
            raise HTTPException(status_code=409, detail="voucher_being_processed_try_again")
    except HTTPException:
        raise
    except Exception:
        pass  # Redis unavailable — proceed without distributed lock (DB uniqueness still protects)

    try:
        with db_session() as db:
            # ── Look up voucher ────────────────────────────────────────────────
            try:
                row = db.execute(
                    _text(
                        "SELECT id, discount_cents, discount_pct, description, max_uses, use_count, "
                        "active, min_order_cents, applies_to_skus, expires_at "
                        "FROM vouchers WHERE code = :code"
                    ),
                    {"code": code},
                ).fetchone()
            except Exception:
                row = None

            if not row:
                raise HTTPException(status_code=404, detail="voucher_not_found")

            (
                voucher_id, discount_cents, discount_pct, description,
                max_uses, use_count, active, min_order_cents,
                applies_to_skus_raw, expires_at,
            ) = row

            if not active:
                raise HTTPException(status_code=409, detail="voucher_inactive")

            # ── Expiry check ────────────────────────────────────────────────
            if expires_at:
                from datetime import datetime, timezone as _tz
                try:
                    exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=_tz.utc)
                    if datetime.now(_tz.utc) > exp:
                        raise HTTPException(status_code=409, detail="voucher_expired")
                except HTTPException:
                    raise
                except Exception:
                    pass

            # ── Max-uses check ──────────────────────────────────────────────
            if max_uses and int(use_count or 0) >= int(max_uses):
                raise HTTPException(status_code=409, detail="voucher_exhausted")

            # ── B1/B2: eligibility (min_order_cents + applies_to_skus) before binding ──
            _elig_err = _voucher_eligibility_error(
                min_order_cents, applies_to_skus_raw, int(cart_subtotal_cents or 0), cart_skus
            )
            if _elig_err:
                raise HTTPException(status_code=409, detail=_elig_err)

            # ── Stacking check: only one active voucher per cart ────────────
            try:
                existing = db.execute(
                    _text("SELECT COUNT(*) FROM cart_vouchers WHERE cart_id = :cid AND voided_at IS NULL"),
                    {"cid": cart_id},
                ).scalar()
                if int(existing or 0) >= 1:
                    raise HTTPException(status_code=409, detail="only_one_voucher_per_cart")
            except HTTPException:
                raise
            except Exception:
                pass

            # ── Atomic: cart binding INSERT first, then use_count increment ──
            # Order matters: only charge the use_count if the binding succeeds.
            # INSERT without IGNORE so a duplicate constraint raises immediately.
            binding_id = str(uuid.uuid4())
            try:
                db.execute(
                    _text(
                        "INSERT INTO cart_vouchers (id, cart_id, voucher_id, applied_at) "
                        "VALUES (:id, :cid, :vid, CURRENT_TIMESTAMP)"
                    ),
                    {"id": binding_id, "cid": cart_id, "vid": voucher_id},
                )
            except Exception:
                raise HTTPException(status_code=409, detail="voucher_already_applied_to_cart")

            updated = db.execute(
                _text(
                    "UPDATE vouchers SET use_count = use_count + 1 "
                    "WHERE id = :vid AND (max_uses IS NULL OR use_count < max_uses)"
                ),
                {"vid": voucher_id},
            ).rowcount
            if updated == 0:
                # Concurrent exhaustion: roll back the binding we just inserted.
                db.execute(_text("DELETE FROM cart_vouchers WHERE id = :id"), {"id": binding_id})
                raise HTTPException(status_code=409, detail="voucher_exhausted_concurrent")

            try:
                db.commit()
            except Exception as exc:
                # B5: a swallowed commit failure told the caller the voucher applied while the
                # DB rolled back. Surface it — the binding+increment must persist or fail loud.
                _vlog.error("voucher commit failed code=%s cart=%s: %s", code, cart_id, exc)
                raise HTTPException(status_code=503, detail="voucher_commit_failed")

        return {
            "voucher_id": str(voucher_id),
            "code": code,
            "discount_cents": int(discount_cents or 0),
            "discount_pct": float(discount_pct or 0.0),
            "description": str(description or ""),
        }
    finally:
        # Always release the distributed lock
        if lock_acquired and redis_client is not None:
            try:
                redis_client.delete(lock_key)
            except Exception:
                pass


@router.post("/voucher")
def apply_voucher(
    payload: VoucherPayload,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Apply a discount voucher code to the user's active cart.

    Feature-flagged via VOUCHER_ENDPOINT_ENABLED=1 (default: disabled).
    Tables are created lazily on first call so startup is never blocked.
    Rate limiting, SETNX distributed lock, and atomic DB update prevent
    race conditions, replay attacks, and voucher stacking.
    """
    if not _VOUCHER_ENABLED:
        raise HTTPException(status_code=404, detail="voucher_endpoint_not_enabled")
    # Lazy schema creation: safe to call on every request (IF NOT EXISTS).
    try:
        _ensure_voucher_tables()
    except Exception:
        raise HTTPException(status_code=503, detail="voucher_schema_unavailable")
    with tracer.start_as_current_span("cart.apply_voucher"):
        signal = _guard_cart_request(
            surface="cart.apply_voucher",
            uid=payload.uid,
            sku_values=[],
            quantity_values=[],
        )
        cart_id, items, _ = _get_or_create_cart(payload.uid)
        _log_cart_security_scan(
            trace_id=_cart_trace_id(cart_id),
            source_id="cart.apply_voucher",
            signal=signal,
        )
        # Hydrate BEFORE applying the voucher so eligibility (min_order / applies_to_skus)
        # is enforced against the real cart subtotal + SKUs (B1/B2).
        hydrated = _hydrate(items)
        _cart_skus = [str(it.get("sku")) for it in items if it.get("sku")]
        voucher = _apply_voucher_atomic(
            cart_id=cart_id,
            uid=payload.uid,
            code=payload.code,
            cart_subtotal_cents=int(hydrated.get("subtotal_cents", 0) or 0),
            cart_skus=_cart_skus,
        )
        # Apply discount to subtotal
        discount_cents = int(voucher.get("discount_cents") or 0)
        if not discount_cents:
            pct = float(voucher.get("discount_pct") or 0.0)
            discount_cents = int(round(hydrated.get("subtotal_cents", 0) * pct / 100.0))
        hydrated["discount_cents"] = discount_cents
        hydrated["total_cents"] = max(0, hydrated.get("subtotal_cents", 0) - discount_cents)
        hydrated["voucher"] = voucher
        hydrated["trace_id"] = _cart_trace_id(cart_id)
        return {"cart_id": cart_id, **hydrated}
