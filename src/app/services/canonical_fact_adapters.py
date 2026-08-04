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

from src.app.services.market_facts import (
    MarketFactRejected,
    record_atp_fact,
    record_marketing_event,
)


def _record(writer, db, fact: Dict[str, Any]) -> tuple[int, int]:
    """Return (written, quarantined); one rejected row must not abort its source batch."""
    try:
        return int(writer(db, fact, commit=False)), 0
    except MarketFactRejected as exc:
        return 0, int(exc.quarantined)


def _iso(value: Any) -> str | None:
    """Preserve source event time; ingestion time must never impersonate it."""
    raw = str(value or "").strip()
    return raw or None


def _subject_hash(value: Any) -> str | None:
    raw = str(value or "").strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else None


def _lines(raw: Any) -> Iterable[Dict[str, Any]]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        value = []
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _order_facts(db, tenant_id: str, limit: int) -> tuple[int, int]:
    rows = db.execute(text("""
        SELECT o.id, d.id, o.customer_id, o.guest_email_hash, o.total_cents, o.currency,
               o.status, o.created_at, o.updated_at, d.line_items
        FROM orders o JOIN draft_orders d ON d.id=o.draft_order_id
        WHERE d.tenant_id=:tenant
          AND o.status IN ('paid','shipped','delivered','returned','refunded','chargebacked')
        ORDER BY COALESCE(o.updated_at,o.created_at) DESC LIMIT :lim
    """), {"tenant": tenant_id, "lim": int(limit)}).fetchall()
    written = rejected = 0
    for row in rows:
        order_id, draft_id, customer_id, guest_hash, total, currency, status, created, updated, raw_lines = row
        lines = list(_lines(raw_lines))
        for index, line in enumerate(lines):
            sku = str(line.get("sku") or "").strip()
            quantity = max(1, int(line.get("quantity") or 1))
            if not sku:
                continue
            unit = int(line.get("price_cents") or 0)
            allocated_value = unit * quantity if unit else (
                int(total) if len(lines) == 1 and total is not None else None)
            # The purchase identity is invariant across paid -> shipped -> delivered. Using
            # the current state in this key triple-counted revenue when the adapter reran.
            record_id = f"{order_id}:purchase:{index}:{sku}"
            accepted, quarantined = _record(record_marketing_event, db, {
                "tenant_id": tenant_id, "deduplication_id": f"orders:{record_id}",
                "event_type": "purchase",
                "subject_hash": str(guest_hash or "") or _subject_hash(customer_id),
                "session_id": str(order_id), "sku": sku, "value": allocated_value,
                "currency": str(currency or "").upper() or None, "quantity": quantity,
                "consent_state": "not_required", "source_system": "orders",
                "source_record_id": record_id, "occurred_at": _iso(created),
                "provenance_chain": [f"orders/{order_id}", f"draft_orders/{draft_id}/line/{index}"],
                "confidence": 1.0, "freshness_policy": "transactional_record",
            })
            written += accepted
            rejected += quarantined
            if str(status) in {"returned", "refunded", "chargebacked"}:
                adjustment_type = "return" if str(status) == "returned" else "refund"
                adjustment_id = f"{order_id}:reversal:{index}:{sku}"
                accepted, quarantined = _record(record_marketing_event, db, {
                    "tenant_id": tenant_id,
                    "deduplication_id": f"orders:{adjustment_id}",
                    "event_type": adjustment_type,
                    "subject_hash": str(guest_hash or "") or _subject_hash(customer_id),
                    "session_id": str(order_id), "sku": sku, "value": allocated_value,
                    "currency": str(currency or "").upper() or None, "quantity": quantity,
                    "consent_state": "not_required", "source_system": "orders",
                    "source_record_id": adjustment_id, "occurred_at": _iso(updated),
                    "provenance_chain": [
                        f"orders/{order_id}",
                        f"draft_orders/{draft_id}/line/{index}",
                    ],
                    "confidence": 1.0, "freshness_policy": "transactional_record",
                })
                written += accepted
                rejected += quarantined
    return written, rejected


def _interaction_facts(db, tenant_id: str, limit: int) -> tuple[int, int]:
    # Inspect through the current transaction. Engine-level reflection can open/rollback a
    # second connection that is the same DB-API connection under in-memory SQLite.
    columns = {str(name) for name in db.execute(
        text("SELECT * FROM recommend_interactions WHERE 1=0")).keys()}
    required = {"tenant_id", "consent_state"}
    if not required.issubset(columns):
        raise RuntimeError("recommend_interactions tenant/consent schema unavailable")
    rows = db.execute(text("""
        SELECT id, event_time, uid_hash, sku, action, surface, trace_id, context_json,
               tenant_id, consent_state
        FROM recommend_interactions
        WHERE tenant_id=:tenant
        ORDER BY event_time DESC LIMIT :lim
    """), {"tenant": tenant_id, "lim": int(limit)}).fetchall()
    event_map = {
        "view": "view_item", "impression": "view_item", "click": "select_item",
        "add": "add_to_cart", "add_to_cart": "add_to_cart", "accepted": "add_to_cart",
    }
    written = rejected = 0
    for row in rows:
        if written + rejected >= int(limit):
            break
        rid, event_time, uid_hash, sku, action, surface, trace_id, raw_context, row_tenant, consent = row
        try:
            context = json.loads(raw_context or "{}") if isinstance(raw_context, str) else (raw_context or {})
        except (TypeError, ValueError):
            context = {}
        event_type = event_map.get(str(action or "").lower())
        if str(row_tenant) != tenant_id or not event_type or not sku:
            continue
        accepted, quarantined = _record(record_marketing_event, db, {
            "tenant_id": tenant_id, "deduplication_id": f"cart:{rid}", "event_type": event_type,
            "subject_hash": str(uid_hash or "") or None, "session_id": context.get("session_id"),
            "sku": str(sku), "channel": str(surface or "recommendation"),
            "consent_state": str(consent or "unknown"),
            "source_system": "cart", "source_record_id": str(rid), "occurred_at": _iso(event_time),
            "provenance_chain": [f"recommend_interactions/{rid}", f"trace/{trace_id}"],
            "confidence": 1.0, "freshness_policy": "behavioral_event",
        })
        written += accepted
        rejected += quarantined
    return written, rejected


def _inventory_facts(db, tenant_id: str, limit: int) -> tuple[int, int]:
    rows = db.execute(text("""
        SELECT sku, location_id, on_hand, reserved, available, source, updated_at
        FROM inventory_level WHERE tenant_id=:tenant ORDER BY updated_at DESC LIMIT :lim
    """), {"tenant": tenant_id, "lim": int(limit)}).fetchall()
    written = rejected = 0
    for sku, location, on_hand, reserved, available, source, observed in rows:
        stamp = _iso(observed)
        record_id = f"{sku}:{location}:{stamp}"
        accepted, quarantined = _record(record_atp_fact, db, {
            "tenant_id": tenant_id, "deduplication_id": f"inventory_level:{record_id}",
            "material_id": str(sku), "sku": str(sku), "location_id": str(location or "default"),
            "on_hand_quantity": int(on_hand or 0), "committed_quantity": int(reserved or 0),
            "confirmed_quantity": int(available if available is not None else (on_hand or 0) - (reserved or 0)),
            "source_system": "inventory_level", "source_record_id": record_id,
            "observed_at": stamp, "provenance_chain": [f"inventory_level/{sku}/{location}"],
            "confidence": 1.0, "freshness_policy": "max_age:86400",
        })
        written += accepted
        rejected += quarantined
    return written, rejected


def _supplier_quote_facts(db, tenant_id: str, limit: int) -> tuple[int, int]:
    rows = db.execute(text("""
        SELECT id, case_id, state_json, valid_from
        FROM fulfillment_case_version
        WHERE tenant_id=:tenant AND event='supplier_quote_validated'
        ORDER BY valid_from DESC LIMIT :lim
    """), {"tenant": tenant_id, "lim": int(limit)}).fetchall()
    written = rejected = 0
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
        accepted, quarantined = _record(record_atp_fact, db, {
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
        })
        written += accepted
        rejected += quarantined
    return written, rejected


def backfill_canonical_facts(db, *, tenant_id: str, limit: int = 1000,
                             commit: bool = True) -> Dict[str, Any]:
    """Materialize real operational records. Missing optional source tables are reported, not hidden."""
    if not str(tenant_id or "").strip():
        raise ValueError("tenant_id is required")
    counts: Dict[str, int] = {}
    rejected_counts: Dict[str, int] = {}
    errors: Dict[str, str] = {}
    for name, adapter in (
        ("orders", _order_facts), ("cart", _interaction_facts),
        ("inventory", _inventory_facts), ("supplier_quotes", _supplier_quote_facts),
    ):
        try:
            counts[name], rejected_counts[name] = adapter(db, str(tenant_id), int(limit))
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
    if commit:
        db.commit()
    return {"tenant_id": str(tenant_id), "written": sum(counts.values()),
            "written_by_source": counts, "quarantined": sum(rejected_counts.values()),
            "quarantined_by_source": rejected_counts, "errors": errors}


def canonical_source_health(db, *, tenant_id: str) -> Dict[str, Any]:
    """Read-only onboarding/reconciliation status for one tenant's governed feeds."""
    if not str(tenant_id or "").strip():
        raise ValueError("tenant_id is required")
    sources: Dict[tuple[str, str], Dict[str, Any]] = {}
    source_errors = []
    for family, table, time_column in (
        ("inventory_atp", "inventory_atp_fact", "observed_at"),
        ("marketing_event", "marketing_event_fact", "occurred_at"),
    ):
        try:
            rows = db.execute(text(
                f"SELECT source_system, COUNT(*), MAX({time_column}) FROM {table} "
                "WHERE tenant_id=:tenant AND status='active' GROUP BY source_system"
            ), {"tenant": tenant_id}).fetchall()
        except Exception as exc:
            rows = []
            source_errors.append({
                "family": family,
                "source_system": None,
                "error": type(exc).__name__,
                "detail": str(exc)[:240],
            })
        for source, count, latest in rows:
            key = (family, str(source or "unknown"))
            sources[key] = {
                "family": family,
                "source_system": key[1],
                "active_records": int(count or 0),
                "latest_observed_at": str(latest or "") or None,
                "quarantined_records": 0,
                "quarantine_reasons": {},
            }
    try:
        rows = db.execute(text("""
            SELECT source_system, COUNT(*), MAX(actual_observed_at)
            FROM forecast_actual_pair
            WHERE tenant_id=:tenant AND status='active'
              AND sealed_by IS NOT NULL AND sealed_by <> ''
            GROUP BY source_system
        """), {"tenant": tenant_id}).fetchall()
    except Exception:
        # Forecast evidence is an optional onboarding family. A missing table means
        # not configured; core canonical fact tables above still fail health loudly.
        rows = []
    for source, count, latest in rows:
        key = ("sealed_forecast_actual", str(source or "unknown"))
        sources[key] = {
            "family": key[0],
            "source_system": key[1],
            "active_records": int(count or 0),
            "latest_observed_at": str(latest or "") or None,
            "quarantined_records": 0,
            "quarantine_reasons": {},
        }
    try:
        quarantines = db.execute(text("""
            SELECT family, COALESCE(source_system,'unknown'), reason_code, COUNT(*),
                   MAX(quarantined_at)
            FROM market_fact_quarantine
            WHERE tenant_id=:tenant
            GROUP BY family, COALESCE(source_system,'unknown'), reason_code
        """), {"tenant": tenant_id}).fetchall()
    except Exception as exc:
        quarantines = []
        source_errors.append({
            "family": "quarantine",
            "source_system": None,
            "error": type(exc).__name__,
            "detail": str(exc)[:240],
        })
    for family, source, reason, count, latest in quarantines:
        normalized_family = {
            "atp": "inventory_atp",
            "marketing": "marketing_event",
        }.get(str(family), str(family))
        key = (normalized_family, str(source))
        row = sources.setdefault(key, {
            "family": key[0],
            "source_system": key[1],
            "active_records": 0,
            "latest_observed_at": None,
            "quarantined_records": 0,
            "quarantine_reasons": {},
        })
        row["quarantined_records"] += int(count or 0)
        row["quarantine_reasons"][str(reason)] = int(count or 0)
        row["latest_quarantined_at"] = str(latest or "") or None
    now = datetime.now(timezone.utc)
    for row in sources.values():
        latest = row.get("latest_observed_at")
        age_hours = None
        if latest:
            try:
                stamp = datetime.fromisoformat(str(latest).replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                age_hours = max(0.0, (now - stamp.astimezone(timezone.utc)).total_seconds() / 3600)
            except ValueError:
                age_hours = None
        row["age_hours"] = round(age_hours, 2) if age_hours is not None else None
        row["status"] = (
            "quarantined_only" if not row["active_records"] and row["quarantined_records"]
            else "stale" if age_hours is None or age_hours > 24
            else "healthy"
        )
    expected = {
        "inventory_atp": {
            "label": "ERP / WMS availability",
            "required_for": ["ATP coverage", "weeks of supply", "replenishment"],
            "required_fields": ["sku", "location", "on_hand", "committed", "observed_at"],
        },
        "marketing_event": {
            "label": "Consented commerce events",
            "required_for": ["conversion", "attribution", "RFM estimates"],
            "required_fields": [
                "event_type", "occurred_at", "deduplication_id",
                "consent_state", "provenance_chain",
            ],
        },
        "landed_inventory_valuation": {
            "label": "Landed inventory valuation",
            "required_for": ["GMROI", "margin after returns"],
            "required_fields": [
                "sku", "location", "quantity", "landed_unit_cost",
                "currency", "valuation_at", "source_document_id",
            ],
        },
        "matched_procurement_documents": {
            "label": "Matched quote / PO / invoice",
            "required_for": ["purchase price variance"],
            "required_fields": [
                "match_id", "quote_id", "purchase_order_id", "invoice_id",
                "unit_cost", "currency",
            ],
        },
        "sealed_forecast_actual": {
            "label": "Sealed forecast versus actual",
            "required_for": ["forecast WAPE", "earned autonomy"],
            "required_fields": [
                "pair_key", "target_window", "forecast", "actual",
                "provenance_chain", "sealed_by",
            ],
        },
    }
    configured_families = {row["family"] for row in sources.values()}
    onboarding = [
        {
            "family": family,
            **contract,
            "status": "connected" if family in configured_families else "not_configured",
        }
        for family, contract in expected.items()
    ]
    ordered = sorted(sources.values(), key=lambda row: (row["family"], row["source_system"]))
    return {
        "tenant_id": str(tenant_id),
        "sources": ordered,
        "onboarding": onboarding,
        "active_records": sum(row["active_records"] for row in ordered),
        "quarantined_records": sum(row["quarantined_records"] for row in ordered),
        "source_errors": source_errors,
        "status": (
            "error" if source_errors
            else "unconfigured" if not ordered
            else "degraded" if any(row["status"] != "healthy" for row in ordered)
            else "healthy"
        ),
    }
