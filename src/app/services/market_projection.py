"""Portable assembly of SKU-scoped market projections from canonical facts."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable

from sqlalchemy import text

from src.app.services.market_analysis import detect_bulk_order_frequency, detect_velocity_dsi


def _as_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _recent(rows: Iterable[Dict[str, Any]], key: str, since: datetime) -> list[Dict[str, Any]]:
    return [row for row in rows if (_as_utc(row.get(key)) or datetime.min.replace(tzinfo=timezone.utc)) >= since]


def load_projection_inputs(db, *, tenant_id: str, window_days: int = 30) -> Dict[str, Any]:
    """Load facts without database-specific date arithmetic."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=max(1, int(window_days)))
    sales_rows: list[Dict[str, Any]] = []
    inventory_rows: list[Dict[str, Any]] = []
    case_rows: list[Dict[str, Any]] = []
    try:
        rows = db.execute(text(
            "SELECT sku, quantity, event_time FROM sales_metrics")).fetchall()
        sales_rows = _recent([
            {"sku": row[0], "quantity": row[1], "event_time": row[2]} for row in rows
        ], "event_time", since)
    except Exception:
        pass
    try:
        rows = db.execute(text(
            "SELECT sku, on_hand, reserved, available, updated_at FROM inventory_level "
            "WHERE COALESCE(tenant_id,'default')=:tenant"), {"tenant": tenant_id}).fetchall()
        inventory_rows = [
            {"sku": row[0], "on_hand": row[1], "reserved": row[2],
             "available": row[3], "updated_at": row[4]} for row in rows
        ]
    except Exception:
        pass
    try:
        rows = db.execute(text(
            "SELECT f.id, v.state_json, v.valid_from FROM fulfillment_case f "
            "JOIN fulfillment_case_version v ON v.case_id=f.id "
            "AND v.valid_from=(SELECT MAX(v2.valid_from) FROM fulfillment_case_version v2 "
            "                  WHERE v2.case_id=f.id) "
            "WHERE COALESCE(f.tenant_id,'default')=:tenant"),
            {"tenant": tenant_id}).fetchall()
        for case_id, raw, occurred_at in rows:
            try:
                state = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            except Exception:
                state = {}
            for line in state.get("order_lines") or []:
                case_rows.append({
                    "case_id": case_id, "sku": line.get("item_ref"),
                    "quantity": line.get("quantity"), "occurred_at": occurred_at,
                })
        case_rows = _recent(case_rows, "occurred_at", now - timedelta(days=90))
    except Exception:
        pass
    return {"sales": sales_rows, "inventory": inventory_rows, "cases": case_rows, "as_of": now.isoformat()}


def projections(db, *, tenant_id: str = "default", window_days: int = 30) -> Dict[str, Dict[str, Any]]:
    inputs = load_projection_inputs(db, tenant_id=tenant_id, window_days=window_days)
    velocity = detect_velocity_dsi(inputs["sales"], inputs["inventory"], window_days=window_days)
    bulk = detect_bulk_order_frequency(inputs["cases"], window_days=90)
    for sku, item in velocity.items():
        item["bulk_frequency"] = bulk.get(sku, {
            "subject_id": sku, "window_days": 90, "bulk_order_count": 0,
            "bulk_units_requested": 0, "orders_per_30d": 0.0,
        })
        item["as_of"] = inputs["as_of"]
        item["confidence"] = "seeded_demo" if inputs["sales"] else "insufficient_data"
    return velocity
