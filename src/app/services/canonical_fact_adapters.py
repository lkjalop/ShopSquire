"""Idempotent adapters from operational commerce records to governed canonical facts.

The adapters read committed system-of-record rows. They do not synthesize buyer behavior and
never make replenishment, ranking, pricing, or supplier decisions.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from sqlalchemy import text

from src.app.services.market_facts import record_atp_fact, record_marketing_event


def _iso(value: Any) -> str:
    raw = str(value or "").strip()
    return raw or datetime.now(timezone.utc).isoformat()


def _subject_hash(value: Any) -> str | None:
    raw = str(value or "").strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else None


def _lines(raw: Any) -> Iterable[Dict[str, Any]]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        value = []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _order_facts(db, tenant_id: str, limit: int) -> int:
    rows = db.execute(text("""
        SELECT o.id, d.id, o.customer_id, o.guest_email_hash, o.total_cents, o.currency,
               o.status, o.created_at, o.updated_at, d.line_items
        FROM orders o JOIN draft_orders d ON d.id=o.draft_order_id
        WHERE d.tenant_id=:tenant
          AND o.status IN ('paid','shipped','delivered','returned','refunded','chargebacked')
        ORDER BY COALESCE(o.updated_at,o.created_at) DESC LIMIT :lim
    """), {"tenant": tenant_id, "lim": int(limit)}).fetchall()
    written = 0
    for row in rows:
        order_id, draft_id, customer_id, guest_hash, total, currency, status, created, updated, raw_lines = row
        event_type = "return" if str(status) == "returned" else (
            "refund" if str(status) in {"refunded", "chargebacked"} else "purchase")
        for index, line in enumerate(_lines(raw_lines)):
            sku = str(line.get("sku") or "").strip()
            quantity = max(1, int(line.get("quantity") or 1))
            if not sku:
                continue
            unit = int(line.get("price_cents") or 0)
            record_id = f"{order_id}:{status}:{index}:{sku}"
            written += int(record_marketing_event(db, {
                "tenant_id": tenant_id, "deduplication_id": f"orders:{record_id}",
                "event_type": event_type, "subject_hash": str(guest_hash or "") or _subject_hash(customer_id),
                "session_id": str(order_id), "sku": sku, "value": unit * quantity if unit else total,
                "currency": str(currency or "USD").upper(), "quantity": quantity,
                "consent_state": "not_required", "source_system": "orders",
                "source_record_id": record_id, "occurred_at": _iso(updated or created),
                "provenance_chain": [f"orders/{order_id}", f"draft_orders/{draft_id}/line/{index}"],
                "confidence": 1.0, "freshness_policy": "transactional_record",
            }, commit=False))
    return written


def _interaction_facts(db, tenant_id: str, limit: int) -> int:
    rows = db.execute(text("""
        SELECT id, event_time, uid_hash, sku, action, surface, trace_id, context_json
        FROM recommend_interactions ORDER BY event_time DESC LIMIT :lim
    """), {"lim": int(limit)}).fetchall()
    event_map = {
        "view": "view_item", "impression": "view_item", "click": "select_item",
        "add": "add_to_cart", "add_to_cart": "add_to_cart", "accepted": "add_to_cart",
    }
    written = 0
    for row in rows:
        rid, event_time, uid_hash, sku, action, surface, trace_id, raw_context = row
        try:
            context = json.loads(raw_context or "{}") if isinstance(raw_context, str) else (raw_context or {})
        except (TypeError, ValueError):
            context = {}
        row_tenant = str(context.get("tenant_id") or "default")
        event_type = event_map.get(str(action or "").lower())
        if row_tenant != tenant_id or not event_type or not sku:
            continue
        written += int(record_marketing_event(db, {
            "tenant_id": tenant_id, "deduplication_id": f"cart:{rid}", "event_type": event_type,
            "subject_hash": str(uid_hash or "") or None, "session_id": context.get("session_id"),
            "sku": str(sku), "channel": str(surface or "recommendation"),
            "consent_state": str(context.get("consent_state") or "not_required"),
            "source_system": "cart", "source_record_id": str(rid), "occurred_at": _iso(event_time),
            "provenance_chain": [f"recommend_interactions/{rid}", f"trace/{trace_id}"],
            "confidence": 1.0, "freshness_policy": "behavioral_event",
        }, commit=False))
    return written


def _inventory_facts(db, tenant_id: str, limit: int) -> int:
    rows = db.execute(text("""
        SELECT sku, location_id, on_hand, reserved, available, source, updated_at
        FROM inventory_level WHERE tenant_id=:tenant ORDER BY updated_at DESC LIMIT :lim
    """), {"tenant": tenant_id, "lim": int(limit)}).fetchall()
    written = 0
    for sku, location, on_hand, reserved, available, source, observed in rows:
        stamp = _iso(observed)
        record_id = f"{sku}:{location}:{stamp}"
        written += int(record_atp_fact(db, {
            "tenant_id": tenant_id, "deduplication_id": f"inventory_level:{record_id}",
            "material_id": str(sku), "sku": str(sku), "location_id": str(location or "default"),
            "on_hand_quantity": int(on_hand or 0), "committed_quantity": int(reserved or 0),
            "confirmed_quantity": int(available if available is not None else (on_hand or 0) - (reserved or 0)),
            "source_system": "inventory_level", "source_record_id": record_id,
            "observed_at": stamp, "provenance_chain": [f"inventory_level/{sku}/{location}"],
            "confidence": 1.0, "freshness_policy": "max_age:86400",
        }, commit=False))
    return written


def _supplier_quote_facts(db, tenant_id: str, limit: int) -> int:
    rows = db.execute(text("""
        SELECT id, case_id, state_json, valid_from
        FROM fulfillment_case_version
        WHERE tenant_id=:tenant AND event='supplier_quote_validated'
        ORDER BY valid_from DESC LIMIT :lim
    """), {"tenant": tenant_id, "lim": int(limit)}).fetchall()
    written = 0
    for version_id, case_id, raw_state, observed in rows:
        try:
            state = json.loads(raw_state or "{}") if isinstance(raw_state, str) else (raw_state or {})
        except (TypeError, ValueError):
            state = {}
        quote = state.get("validated_quote") or {}
        availability = state.get("availability") or {}
        draft = state.get("draft") or {}
        scope = draft.get("commercial_scope") or {}
        sku = str(availability.get("item_ref") or scope.get("item_ref") or "").strip()
        if not sku or not quote.get("quoted_quantity"):
            continue
        written += int(record_atp_fact(db, {
            "tenant_id": tenant_id, "deduplication_id": f"supplier_quote:{version_id}",
            "material_id": sku, "sku": sku,
            "requested_quantity": int(scope.get("quantity") or availability.get("shortfall") or 0),
            "requested_date": (state.get("requirements") or {}).get("needed_by"),
            "confirmed_quantity": int(quote.get("quoted_quantity") or 0),
            "confirmed_date": quote.get("estimated_delivery_at") or quote.get("dispatch_ready_at"),
            "lead_time_days": quote.get("lead_time_days"),
            "supplier_id": state.get("supplier_ref") or draft.get("supplier_ref"),
            "source_system": "supplier_quote", "source_record_id": str(version_id),
            "observed_at": _iso(observed),
            "provenance_chain": [f"fulfillment_case/{case_id}", f"version/{version_id}"],
            "confidence": float(quote.get("confidence") or 1.0),
            "freshness_policy": "quote_validity",
        }, commit=False))
    return written


def backfill_canonical_facts(db, *, tenant_id: str, limit: int = 1000,
                             commit: bool = True) -> Dict[str, Any]:
    """Materialize real operational records. Missing optional source tables are reported, not hidden."""
    if not str(tenant_id or "").strip():
        raise ValueError("tenant_id is required")
    counts: Dict[str, int] = {}
    errors: Dict[str, str] = {}
    for name, adapter in (
        ("orders", _order_facts), ("cart", _interaction_facts),
        ("inventory", _inventory_facts), ("supplier_quotes", _supplier_quote_facts),
    ):
        try:
            counts[name] = adapter(db, str(tenant_id), int(limit))
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
    if commit:
        db.commit()
    return {"tenant_id": str(tenant_id), "written": sum(counts.values()),
            "written_by_source": counts, "errors": errors}
