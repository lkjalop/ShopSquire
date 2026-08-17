from __future__ import annotations

import json
import os
import uuid
from typing import Dict, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text as sql_text
from pydantic import BaseModel, EmailStr

from src.app.models.db import db_session, get_engine, get_db
from src.app.observability.tracing import get_tracer
from src.app.repositories.catalog import CatalogRepository
from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.services.pii_crypto import encrypt_pii, pii_hash
from src.app.services.inventory_guard import reserve_inventory_for_order, release_inventory_for_order


def _record_post_order_outcome(
    db, *, order_id: str, kind: str, status: str, authority: str,
) -> None:
    """Best-effort graph projection; the canonical order transition remains authoritative."""
    try:
        from src.app.platform.tenant_context import current_tenant_id
        from src.app.services.hippograph_journey_producers import post_order_outcome_edge
        from src.app.services.hippograph_journey_store import persist_journey_edges

        tenant_id = str(current_tenant_id() or "default")
        edge = post_order_outcome_edge(
            tenant_id=tenant_id, order_id=order_id, outcome_kind=kind,
            outcome_id=f"{order_id}:{status}", status=status, source_authority=authority,
        )
        persist_journey_edges(db, [edge], tenant_id=tenant_id, case_id=order_id)
    except Exception:
        # Graph evidence is retryable and must never undo a committed order transition.
        try:
            db.rollback()
        except Exception:
            pass


def _record_commercial_outcome(db, *, order_id: str, status: str) -> None:
    """Project a committed order transition into the PII-free outcome ledger."""

    try:
        from src.app.services.commercial_outcome_ledger import (
            record_order_transition_outcome,
        )

        record_order_transition_outcome(db, order_id=order_id, status=status)
    except Exception as exc:
        # The canonical order transition has already committed. Emit a typed
        # partial failure so outcome projection can be replayed without lying
        # to the buyer or rolling the order back.
        from src.app.services.safe_stage import record_partial_failure

        record_partial_failure("commercial_outcome_projection", exc, trace_id=order_id)


router = APIRouter(prefix="/api/v1/orders", tags=["orders"])
tracer = get_tracer("orders-router")


class OrderItem(BaseModel):
    sku: str
    quantity: int = 1


class OrderCreate(BaseModel):
    uid: str
    items: List[OrderItem]
    customer_id: str | None = None
    guest_email: EmailStr | None = None
    # E1 — attribution: the recommendation trace_id the cart carried, so the order can be
    # linked back to the decision that produced it. Optional (direct orders leave it null).
    trace_id: str | None = None

class OrderStatusUpdate(BaseModel):
    status: str


class GuestLookupPayload(BaseModel):
    order_id: str
    email: EmailStr

ALLOWED_TRANSITIONS = {
    "created": {"paid", "cancelled"},
    "paid": {"shipped"},
    "shipped": {"delivered"},
    "delivered": {"return_requested"},
    "return_requested": {"returned"},
}

def _get_order_status(order_id: str, db=None) -> str:
    from sqlalchemy import text as _text
    # Prefer request/injected session first so handlers read from the app-bound
    # engine in tests that create multiple app instances.
    row = None
    if db is not None:
        try:
            row = db.execute(_text("SELECT status FROM orders WHERE id = :id"), {"id": order_id}).fetchone()
        except Exception:
            row = None

    try:
        if not row:
            with db_session() as _db:
                row = _db.execute(_text("SELECT status FROM orders WHERE id = :id"), {"id": order_id}).fetchone()
    except Exception:
        pass

    # As a last-ditch fallback, try engine-level connect (some tests insert
    # rows directly on an engine instance and may require a connect())
    if not row:
        try:
            eng = get_engine()
            with eng.connect() as conn:
                row2 = conn.execute(_text("SELECT status FROM orders WHERE id = :id"), {"id": order_id}).fetchone()
                if row2:
                    row = row2
        except Exception:
            pass

    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    # Row may be a tuple, Row, or mapping. Normalize to string status value.
    try:
        if hasattr(row, "_mapping"):
            return row._mapping.get("status")
        try:
            return row[0]
        except Exception:
            pass
        if isinstance(row, dict):
            return row.get("status")
    except Exception:
        pass
    return str(row)

def create_order_core(db, *, uid: str, items: list, customer_id: str | None = None,
                      guest_email: str | None = None, trace_id: str | None = None) -> Dict:
    """Order creation shared by the merchant route and the public checkout bridge (P0-A:
    checkout-initiate creates the order server-side so the customer path yields a REAL order row
    and the webhook's created→paid transition is reachable). ``items`` accepts OrderItem models or
    {sku, quantity} dicts. Prices are ALWAYS server-side catalog prices. Raises HTTPException."""
    from types import SimpleNamespace
    norm = []
    for i in (items or []):
        sku = getattr(i, "sku", None) or (i.get("sku") if isinstance(i, dict) else None)
        qty = getattr(i, "quantity", None) or (i.get("quantity") if isinstance(i, dict) else 1) or 1
        if sku:
            norm.append(SimpleNamespace(sku=str(sku), quantity=int(qty)))
    req = SimpleNamespace(uid=str(uid or ""), items=norm, customer_id=customer_id,
                          guest_email=guest_email, trace_id=trace_id)
    with tracer.start_as_current_span("orders.create"):
        if not req.items:
            raise HTTPException(status_code=400, detail="Items required")
        repo = CatalogRepository()
        line_items = []
        total_cents = 0
        def _fallback_product_price_cents(sku: str) -> int | None:
            try:
                from src.app.routers.ui_storefront import _get_products
                for p in _get_products():
                    if str(p.get("sku")) == str(sku):
                        price = p.get("price")
                        if price is None:
                            return None
                        return int(price) * 100
            except Exception:
                return None
            return None
        with tracer.start_as_current_span("orders.catalog_lookup"):
            for it in req.items:
                sku = it.sku
                qty = int(it.quantity or 1)
                if not sku:
                    continue
                use_fallback_first = os.getenv("TEST_USE_FALLBACK_PRODUCTS", "0").lower() in ("1", "true", "yes")
                if use_fallback_first:
                    fallback_price = _fallback_product_price_cents(sku)
                    if fallback_price is not None:
                        line_items.append({"sku": sku, "quantity": qty, "price_cents": fallback_price})
                        total_cents += fallback_price * qty
                        continue
                product = repo.get_product_by_sku(sku)
                if not product:
                    fallback_price = _fallback_product_price_cents(sku)
                    if fallback_price is None:
                        raise HTTPException(status_code=400, detail=f"Invalid SKU: {sku}")
                    line_items.append({"sku": sku, "quantity": qty, "price_cents": fallback_price})
                    total_cents += fallback_price * qty
                else:
                    line_items.append({"sku": sku, "quantity": qty, "price_cents": product.price_cents})
                    total_cents += product.price_cents * qty
        if not line_items:
            raise HTTPException(status_code=400, detail="No valid items")

        order_id = str(uuid.uuid4())
        draft_id = str(uuid.uuid4())
        customer_id = req.customer_id or None
        guest_email = None
        guest_email_hash = None
        guest_email_encrypted = None
        if not customer_id and req.guest_email:
            guest_email = req.guest_email.strip().lower()
            guest_email_hash = pii_hash(guest_email)
            guest_email_encrypted = encrypt_pii(guest_email)
        session_uid = customer_id or req.uid
        # Reserve stock before persisting order to prevent negative inventory.
        enforce_reservation = str(os.getenv("INVENTORY_RESERVATION_ENFORCED", "1")).lower() in ("1", "true", "yes")
        strict_untracked = str(os.getenv("INVENTORY_STRICT_UNTRACKED", "0")).lower() in ("1", "true", "yes")
        if enforce_reservation:
            try:
                ok, details = reserve_inventory_for_order(
                    db,
                    order_id=order_id,
                    line_items=[{"sku": li.get("sku"), "quantity": int(li.get("quantity") or 1)} for li in line_items],
                    strict_untracked=strict_untracked,
                )
                if not ok:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    raise HTTPException(status_code=409, detail={"message": "insufficient_stock", **details})
            except HTTPException:
                raise
            except Exception:
                # Fail closed only when strict mode enabled.
                if strict_untracked:
                    raise HTTPException(status_code=500, detail="inventory_reservation_failed")
        # use injected session
        # db is a SQLAlchemy Session provided by Depends(get_db)
        # Insert draft, order and session atomically
        with tracer.start_as_current_span("orders.db_write"):
            from src.app.platform.tenant_context import current_tenant_id
            db.execute(
                sql_text("INSERT INTO draft_orders (id, customer_id, tenant_id, line_items, status) VALUES (:id, :customer_id, :t, :line_items, :status)"),
                {"id": draft_id, "customer_id": customer_id, "t": current_tenant_id(), "line_items": json.dumps(line_items), "status": "draft"},
            )
            db.execute(
                sql_text(
                    "INSERT INTO orders (id, draft_order_id, customer_id, tenant_id, tenant_ownership_status, guest_email, guest_email_hash, guest_email_encrypted, total_cents, currency, status, trace_id) "
                    "VALUES (:id, :draft_id, :customer_id, :tenant_id, 'authoritative_request_context', :guest_email, :guest_email_hash, :guest_email_encrypted, :total_cents, :currency, :status, :trace_id)"
                ),
                {
                    "id": order_id,
                    "draft_id": draft_id,
                    "customer_id": customer_id,
                    "tenant_id": current_tenant_id(),
                    "guest_email": None,
                    "guest_email_hash": guest_email_hash,
                    "guest_email_encrypted": guest_email_encrypted,
                    "total_cents": total_cents,
                    "currency": "USD",
                    "status": "created",
                    "trace_id": req.trace_id,  # E1
                },
            )
            db.execute(
                sql_text(
                    "INSERT INTO order_sessions "
                    "(id, uid, order_id, tenant_id, tenant_ownership_status) "
                    "VALUES (:id, :uid, :order_id, :tenant_id, 'derived_from_tenant_order')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "uid": session_uid,
                    "order_id": order_id,
                    "tenant_id": current_tenant_id(),
                },
            )
            try:
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception:
                    pass

        # E2 — attribution: link this order back to the recommendation decision that produced it
        # (trace_id match first, uid_hash fallback). Isolated session + observable-on-failure;
        # never affects the order result. Flag-gated for parity with E0 capture.
        try:
            from src.app.feature_flags import get_flags as _get_flags
            if (_get_flags() or {}).get("ATTRIBUTION_ENABLED", True):
                from src.app.services.attribution import attribute_order as _attribute_order
                from src.app.deps import hash_uid as _hash_uid
                _attr_uid_hash = _hash_uid(session_uid) if session_uid else None
                _attr_skus = [li.get("sku") for li in line_items if li.get("sku")]
                with db_session() as _attr_db:
                    _attribute_order(
                        _attr_db,
                        order_id=order_id,
                        trace_id=req.trace_id,
                        uid_hash=_attr_uid_hash,
                        value_cents=total_cents,
                        line_skus=_attr_skus,
                        converted_at=datetime.utcnow().isoformat(),
                    )
                    _attr_db.commit()
        except Exception as _e_attr:
            from src.app.services.safe_stage import record_partial_failure as _rpf
            _rpf("attribution_order", _e_attr, trace_id=req.trace_id)

        _record_commercial_outcome(db, order_id=order_id, status="created")
        summary = {"order_id": order_id, "total_cents": total_cents, "created_at": datetime.utcnow().isoformat()}
        return {"created": True, "order_id": order_id, "total_cents": total_cents, "created_at": summary["created_at"], "status": "created", "customer_id": customer_id}


@router.post("/create")
def create_order(req: OrderCreate, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])), db=Depends(get_db)) -> Dict:
    return create_order_core(db, uid=req.uid, items=req.items, customer_id=req.customer_id,
                             guest_email=(str(req.guest_email) if req.guest_email else None),
                             trace_id=req.trace_id)


@router.post("/guest/lookup")
def guest_lookup(payload: GuestLookupPayload, db=Depends(get_db)) -> Dict:
    with tracer.start_as_current_span("orders.guest_lookup"):
        email = payload.email.strip().lower()
        email_h = pii_hash(email)
        row = db.execute(
            """
            SELECT id, total_cents, status, created_at
            FROM orders
            WHERE id = :oid
              AND (
                guest_email_hash = :email_h
                OR LOWER(guest_email) = :email
              )
            """,
            {"oid": payload.order_id, "email": email, "email_h": email_h},
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        return {"order_id": row[0], "total_cents": row[1], "status": row[2], "created_at": str(row[3])}


@router.get("/history")
def order_history(
    uid: str,
    limit: int = 10,
    offset: int = 0,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
    db=Depends(get_db),
) -> Dict:
    with tracer.start_as_current_span("orders.history"):
        limit = max(1, min(int(limit or 10), 50))
        offset = max(0, int(offset or 0))
        try:
            # Use db_session so tests that swap the engine via dbmod.engine
            # will have their inserted rows visible to this query. Inline LIMIT
            # and OFFSET to avoid SQLite binding quirks.
            from sqlalchemy import text as _text
            lim = int(limit + 1)
            off = int(offset)
            sql = (
                "SELECT o.id, o.total_cents, o.status, o.created_at "
                "FROM order_sessions s JOIN orders o ON o.id = s.order_id "
                "WHERE s.uid = :uid ORDER BY s.created_at DESC LIMIT :lim OFFSET :off"
            )
            q_params = {"uid": uid, "lim": lim, "off": off}
            # Prefer db_session so tests that swap the module engine/session
            # see the same data. Use the injected `db` only for writes; some
            # tests insert directly via the engine and require a session bound
            # to the test engine for visibility.
            # Prefer the injected request-bound session for reads to align with test engines
            try:
                rows = db.execute(_text(sql), q_params).fetchall()
                try:
                    import sys
                    sys.stderr.write(f"[orders] injected.bind.url={getattr(getattr(db, 'bind', None), 'url', None)}\n")
                    sys.stderr.flush()
                except Exception:
                    pass
                has_more = len(rows) > limit
                trimmed = rows[:limit]
            except Exception:
                # Fallback to module-level session if injected one fails
                try:
                    with db_session() as _db:
                        rows = _db.execute(_text(sql), q_params).fetchall()
                        try:
                            import sys
                            sys.stderr.write(f"[orders] db_session.bind.url={getattr(_db.bind, 'url', None)}\n")
                            sys.stderr.flush()
                        except Exception:
                            pass
                        has_more = len(rows) > limit
                        trimmed = rows[:limit]
                except Exception:
                    rows = []
                    has_more = False
                    trimmed = []
            # Fallback to engine-level connect if session returns no rows
            if not rows:
                try:
                    eng = get_engine()
                    try:
                        import sys
                        sys.stderr.write(f"[orders] fallback.eng.url={eng.url}\n")
                        sys.stderr.flush()
                    except Exception:
                        pass
                    with eng.connect() as conn:
                        rows2 = conn.execute(_text(sql), q_params).fetchall()
                        has_more = len(rows2) > limit
                        trimmed = rows2[:limit]
                except Exception:
                    pass
            return {
                "orders": [
                    {"order_id": r[0], "total_cents": r[1], "status": r[2], "created_at": str(r[3])}
                    for r in trimmed
                ],
                "has_more": has_more,
                "next_offset": offset + len(trimmed),
            }
        except Exception:
            return {"orders": [], "has_more": False, "next_offset": offset}


@router.get("/list")
def list_orders(limit: int = 50, offset: int = 0, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])), db=Depends(get_db)) -> Dict:
    with tracer.start_as_current_span("orders.list"):
        try:
            # Use db_session for reads so tests that swap the module engine/session
            # see inserted rows. The injected `db` is primarily for writes.
            from sqlalchemy import text as _text
            with db_session() as _db:
                rows = _db.execute(_text("SELECT id, total_cents, status, created_at, updated_at FROM orders ORDER BY created_at DESC LIMIT :limit OFFSET :offset"), {"limit": limit, "offset": offset}).fetchall()
            return {
                "orders": [
                    {
                        "order_id": r[0],
                        "total_cents": r[1],
                        "status": r[2],
                        "created_at": str(r[3]),
                        "updated_at": str(r[4]),
                    }
                    for r in rows
                ]
            }
        except Exception:
            return {"orders": []}


@router.post("/{order_id}/cancel")
def cancel_order(order_id: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])), db=Depends(get_db)) -> Dict:
    with tracer.start_as_current_span("orders.cancel"):
        status = _get_order_status(order_id, db)
        if "cancelled" not in ALLOWED_TRANSITIONS.get(status, set()):
            raise HTTPException(status_code=400, detail=f"Cannot cancel from status {status}")

        # ── Unified Authorization Engine gate (shadow) ──
        # Human-authenticated route (require_role), so enforce_lane=False — there is
        # no autonomous-agent lane to police; the engine provides the unified policy
        # + audit trail. Inert in shadow mode; enforces once flipped to active.
        try:
            from src.app.security.authorization_engine import authorize_action
            _conditions = [] if status is None else ([] if status not in ("shipped", "delivered") else ["order_shipped"])
            if not status:
                _conditions.append("order_not_found")
            _authz = authorize_action(
                "order_modification",
                requester=str(role or "merchant"),
                conditions=_conditions,
                subject_id=order_id,
                idempotency_key=f"cancel:{order_id}",
                enforce_lane=False,
            )
            if _authz.should_block():  # inert in shadow
                raise HTTPException(status_code=409, detail={
                    "error": "authorization_engine_denied",
                    "action": "order_modification",
                    "reason": _authz.reason,
                    "terminal_outcome": _authz.terminal_outcome,
                    "residual": _authz.residual,
                })
        except HTTPException:
            raise
        except Exception:
            pass
        # CAS transition (P0-1c): guard the write on the status we validated so two concurrent
        # transitions can't both win (last-writer-wins would let a `paid` order be silently
        # cancelled). Same pattern as the Stripe webhook (`AND status='created'`). Inventory is
        # released ONLY if we won the transition — never on a lost race (double-release guard).
        res = db.execute(
            sql_text("UPDATE orders SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP "
                     "WHERE id = :id AND status = :expected"),
            {"id": order_id, "expected": status},
        )
        won = int(getattr(res, "rowcount", 0) or 0) > 0
        try:
            if won:
                release_inventory_for_order(db, order_id=order_id)
            db.commit()
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            raise HTTPException(status_code=503, detail="Order cancellation could not be committed") from exc
        if not won:
            # order existed at read (else _get_order_status 404'd) → status changed under us
            raise HTTPException(status_code=409, detail="Order status changed concurrently; please retry")
        _record_post_order_outcome(
            db, order_id=order_id, kind="cancellation", status="cancelled",
            authority="authenticated_order_cancellation",
        )
        _record_commercial_outcome(db, order_id=order_id, status="cancelled")
        return {"cancelled": True, "order_id": order_id}


@router.post("/{order_id}/return")
def return_order(order_id: str, role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])), db=Depends(get_db)) -> Dict:
    with tracer.start_as_current_span("orders.return_request"):
        status = _get_order_status(order_id, db)
        if "return_requested" not in ALLOWED_TRANSITIONS.get(status, set()):
            raise HTTPException(status_code=400, detail=f"Cannot request return from status {status}")
        res = db.execute(
            sql_text("UPDATE orders SET status = 'return_requested', updated_at = CURRENT_TIMESTAMP "
                     "WHERE id = :id AND status = :expected"),   # P0-1c CAS guard
            {"id": order_id, "expected": status},
        )
        try:
            db.commit()
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            raise HTTPException(status_code=503, detail="Return request could not be committed") from exc
        if int(getattr(res, "rowcount", 0) or 0) == 0:
            raise HTTPException(status_code=409, detail="Order status changed concurrently; please retry")
        _record_post_order_outcome(
            db, order_id=order_id, kind="return", status="return_requested",
            authority="authenticated_return_request",
        )
        _record_commercial_outcome(db, order_id=order_id, status="return_requested")
        return {"return_requested": True, "order_id": order_id}


@router.post("/{order_id}/status")
def update_status(
    order_id: str,
    req: OrderStatusUpdate,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
    db=Depends(get_db),
) -> Dict:
    with tracer.start_as_current_span("orders.update_status"):
        target = (req.status or "").strip().lower()
        if target not in {"paid", "shipped", "delivered", "returned"}:
            raise HTTPException(status_code=400, detail="Invalid status")
        from sqlalchemy import text as _text
        current = _get_order_status(order_id, db)
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise HTTPException(status_code=400, detail=f"Cannot move from {current} to {target}")
        res = db.execute(
            _text("UPDATE orders SET status = :status, updated_at = CURRENT_TIMESTAMP "
                  "WHERE id = :id AND status = :expected"),   # P0-1c CAS guard
            {"id": order_id, "status": target, "expected": current},
        )
        try:
            db.commit()
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            raise HTTPException(status_code=503, detail="Order status update could not be committed") from exc
        if int(getattr(res, "rowcount", 0) or 0) == 0:
            raise HTTPException(status_code=409, detail="Order status changed concurrently; please retry")
        if target == "returned":
            _record_post_order_outcome(
                db, order_id=order_id, kind="return", status="returned",
                authority="authenticated_order_status_transition",
            )
        if target in {"paid", "returned"}:
            _record_commercial_outcome(db, order_id=order_id, status=target)
        return {"updated": True, "order_id": order_id, "status": target}
