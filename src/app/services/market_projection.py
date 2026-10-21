"""Portable assembly of SKU-scoped market projections from canonical facts."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Sequence

from sqlalchemy import inspect, text

from src.app.services.decision_log import log_trace_event
from src.app.services.executive_metrics import gmroi_unavailable, inventory_productivity
from src.app.services.market_analysis import detect_bulk_order_frequency, detect_velocity_dsi


def _as_utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _recent(
    rows: Iterable[Dict[str, Any]], key: str, since: datetime, until: datetime,
) -> list[Dict[str, Any]]:
    return [row for row in rows
            if (observed := _as_utc(row.get(key))) is not None and since <= observed <= until]


def _optional_rows(db, table_name: str, statement: str, params: Dict[str, Any] | None = None):
    """Read an optional projection source without poisoning the caller transaction.

    Production databases are migration-first, but sparse demo/test profiles may
    intentionally omit a source table. PostgreSQL marks the whole transaction as
    failed after a missing-table/column query, so a bare ``except`` is not a safe
    fallback. Inspect first and retain a savepoint for schema drift between the
    inspection and the read.
    """
    if not inspect(db.connection()).has_table(table_name):
        return []
    try:
        with db.begin_nested():
            return db.execute(text(statement), params or {}).fetchall()
    except Exception:
        return []


def _current_inventory_rows(db, *, tenant_id: str, now: datetime):
    """Project current physical ATP, never a future order's confirmed quantity.

    Older SQLite fixtures may omit optional validity/safety columns. Their
    observation still has the same one-day bound; malformed declared validity
    fails closed. Filter before selecting the latest location snapshot, and
    compare normalized instants rather than lexically ordered timestamp text.
    """
    schema = inspect(db.connection())
    if not schema.has_table("inventory_atp_fact"):
        return [], "unavailable"
    columns = {column["name"] for column in schema.get_columns("inventory_atp_fact")}
    optional = ", ".join(
        name if name in columns else f"NULL AS {name}"
        for name in ("valid_from", "valid_to", "safety_stock_quantity")
    )
    rows = _optional_rows(db, "inventory_atp_fact", (
        "SELECT sku, location_id, on_hand_quantity, committed_quantity, observed_at, "
        "source_system, confidence, source_record_id, " + optional +
        " FROM inventory_atp_fact WHERE tenant_id=:tenant AND status='active'"
    ), {"tenant": tenant_id})
    latest = {}
    eligible = []
    for row in rows:
        observed = _as_utc(row[4])
        valid_from = _as_utc(row[8]) if row[8] is not None else observed
        valid_to = (_as_utc(row[9]) if row[9] is not None
                    else observed + timedelta(days=1) if observed is not None else None)
        if (observed is None or valid_from is None or valid_to is None
                or not now - timedelta(days=1) <= observed <= now
                or not valid_from <= now < valid_to):
            continue
        counts = (row[2], row[3], row[10] if row[10] is not None else 0)
        if not all(isinstance(value, int) and value >= 0 for value in counts):
            continue
        eligible.append((observed, row, counts))
    for observed, row, (on_hand, reserved, safety) in sorted(
        eligible, key=lambda item: item[0], reverse=True,
    ):
        key = (str(row[0] or ""), str(row[1] or "default"))
        latest.setdefault(key, {
            "sku": row[0], "location_id": row[1], "on_hand": on_hand,
            "reserved": reserved, "available": max(0, on_hand - reserved - safety),
            "updated_at": row[4], "source_system": row[5],
            "confidence": float(row[6] or 0.0), "source_record_id": row[7],
        })
    return list(latest.values()), "observed" if latest else "insufficient_data"


def load_projection_inputs(db, *, tenant_id: str, window_days: int = 30) -> Dict[str, Any]:
    """Load facts without database-specific date arithmetic."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=max(1, int(window_days)))
    sales_rows: list[Dict[str, Any]] = []
    inventory_rows: list[Dict[str, Any]] = []
    case_rows: list[Dict[str, Any]] = []
    rows = _optional_rows(
        db,
        "marketing_event_fact",
        (
            "SELECT sku, quantity, occurred_at, source_system, source_record_id "
            "FROM marketing_event_fact "
            "WHERE tenant_id=:tenant AND event_type='purchase' AND status='active'"
        ),
        {"tenant": tenant_id},
    )
    if rows:
        sales_rows = _recent([
            {"sku": row[0], "quantity": row[1], "event_time": row[2],
             "source_system": row[3], "source_record_id": row[4]} for row in rows
        ], "event_time", since, now)
    # sales_metrics is a legacy, unscoped demo fixture. It may inform only the
    # default demo tenant; it must never bleed into a real tenant projection.
    if (
        not sales_rows
        and tenant_id == "default"
        and inspect(db.connection()).has_table("sales_metrics")
    ):
        rows = _optional_rows(
            db,
            "sales_metrics",
            "SELECT sku, quantity, event_time FROM sales_metrics",
        )
        if rows:
            sales_rows = _recent([
                {"sku": row[0], "quantity": row[1], "event_time": row[2]} for row in rows
            ], "event_time", since, now)
    inventory_rows, inventory_status = _current_inventory_rows(db, tenant_id=tenant_id, now=now)
    rows = _optional_rows(
        db,
        "fulfillment_case",
        (
            "SELECT f.id, v.state_json, v.valid_from FROM fulfillment_case f "
            "JOIN fulfillment_case_version v ON v.case_id=f.id "
            "AND v.valid_from=(SELECT MAX(v2.valid_from) FROM fulfillment_case_version v2 "
            "                  WHERE v2.case_id=f.id) "
            "WHERE COALESCE(f.tenant_id,'default')=:tenant"
        ),
        {"tenant": tenant_id},
    ) if inspect(db.connection()).has_table("fulfillment_case_version") else []
    if rows:
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
        case_rows = _recent(case_rows, "occurred_at", now - timedelta(days=90), now)
    sales_status = (
        "observed" if sales_rows and tenant_id != "default"
        else "simulated" if sales_rows
        else "insufficient_data"
    )
    return {
        "sales": sales_rows, "inventory": inventory_rows, "cases": case_rows,
        "as_of": now.isoformat(), "sales_status": sales_status,
        "inventory_status": inventory_status,
    }


def projections(db, *, tenant_id: str = "default", window_days: int = 30) -> Dict[str, Dict[str, Any]]:
    inputs = load_projection_inputs(db, tenant_id=tenant_id, window_days=window_days)
    velocity = detect_velocity_dsi(inputs["sales"], inputs["inventory"], window_days=window_days)
    bulk = detect_bulk_order_frequency(inputs["cases"], window_days=90)
    for sku, item in velocity.items():
        sales_available = inputs["sales_status"] in {"observed", "simulated"}
        inventory_observed = inputs["inventory_status"] == "observed"
        if not sales_available:
            item.update({
                "units_sold": None, "units_per_day": None, "velocity": None,
                "dsi_days": None, "dead_stock": None,
            })
        if not inventory_observed:
            item.update({
                "stock_on_hand": None, "velocity": None, "dsi_days": None,
                "stockout": None, "dead_stock": None,
            })
        item["measurement_truth"] = {
            "sales": inputs["sales_status"] if sales_available else "not_collected",
            "inventory": "observed" if inventory_observed else (
                "not_disclosed" if inputs["inventory_status"] == "unavailable"
                else "not_collected"
            ),
            "authority": "evidence_only",
        }
        item["bulk_frequency"] = bulk.get(sku)
        item["bulk_frequency_state"] = (
            "derived" if sku in bulk else
            "observed_zero" if inputs["cases"] else
            "not_collected"
        )
        item["as_of"] = inputs["as_of"]
        statuses = {inputs["sales_status"], inputs["inventory_status"]}
        item["status"] = (
            "observed" if statuses == {"observed"}
            else "simulated" if "simulated" in statuses
            else "insufficient_data"
        )
        item["confidence"] = (
            "high" if item["status"] == "observed"
            else "demo_only" if item["status"] == "simulated"
            else "insufficient_data"
        )
        item["source_status"] = {
            "sales": inputs["sales_status"], "inventory": inputs["inventory_status"]}
        source_records = [
            f"{row.get('source_system')}/{row.get('source_record_id')}"
            for row in [*inputs["sales"], *inputs["inventory"]]
            if str(row.get("sku") or "") == sku and row.get("source_record_id")
        ]
        item["metrics"] = [
            (metric.model_copy(update={"status": "simulated"})
             if item["status"] == "simulated" and metric.value is not None
             else metric).model_dump(mode="json")
            for metric in inventory_productivity(
                tenant_id=tenant_id, sku=sku,
                units_sold=int(item.get("units_sold") or 0),
                window_days=window_days,
                available_units=(
                    int(item["stock_on_hand"])
                    if item.get("stock_on_hand") is not None else None),
                source_records=source_records,
            )
        ]
        item["metrics"].append(
            gmroi_unavailable(tenant_id=tenant_id, subject_id=sku).model_dump(mode="json"))
    return velocity


def _projection_demand_trend(projection: Dict[str, Any], units_per_day: float | None) -> str:
    simulated = (projection.get("source_status") or {}).get("sales") == "simulated"
    if projection.get("dead_stock") is True:
        return "simulated_dead_stock" if simulated else "dead_stock"
    if units_per_day is not None and units_per_day > 0:
        return "simulated_sales" if simulated else "observed_sales"
    if units_per_day == 0:
        return "simulated_zero" if simulated else "observed_zero"
    return "not_verified"


def projection_evidence(
    db, *, tenant_id: str, results: Sequence[Dict[str, Any]], window_days: int = 30,
) -> list[Dict[str, Any]]:
    """Build buyer-safe, tenant/SKU-scoped evidence for an ordered slate."""
    by_sku = projections(db, tenant_id=tenant_id, window_days=window_days)
    evidence: list[Dict[str, Any]] = []
    for rank, row in enumerate(results[:10], start=1):
        sku = str((row or {}).get("sku") or "").strip()
        projection = by_sku.get(sku)
        if not projection:
            continue
        units_per_day = (
            float(projection["units_per_day"])
            if projection.get("units_per_day") is not None else None
        )
        evidence.append({
            "tenant_id": tenant_id,
            "sku": sku,
            "rank": rank,
            "demand_trend": _projection_demand_trend(projection, units_per_day),
            "forecast_units_30d": (
                round(units_per_day * 30.0, 2) if units_per_day is not None else None
            ),
            "velocity_dsi_days": projection.get("dsi_days"),
            "stock_position": (
                "stockout" if projection.get("stockout") is True
                else "surplus" if projection.get("dead_stock") is True
                else "balanced" if projection.get("stock_on_hand") is not None
                else "not_verified"
            ),
            "stock_on_hand": projection.get("stock_on_hand"),
            "bulk_frequency": projection.get("bulk_frequency"),
            "bulk_frequency_state": projection.get("bulk_frequency_state"),
            "metrics": projection.get("metrics", []),
            "status": projection.get("status"),
            "source_status": projection.get("source_status"),
            "measurement_truth": projection.get("measurement_truth"),
            "confidence": projection.get("confidence"),
            "as_of": projection.get("as_of"),
            "economics_included": False,
        })
    return evidence


def emit_projection_events(
    db, *, trace_id: str, tenant_id: str, results: Sequence[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    """Persist the same scoped evidence for legacy and V2 recommendation paths."""
    evidence = projection_evidence(db, tenant_id=tenant_id, results=results)
    for payload in evidence:
        log_trace_event(
            trace_id=trace_id, event_type="market_projection", source_type="stage",
            source_id="MarketProjectionStage", target_type="sku",
            target_id=str(payload["sku"]), payload=payload)
    try:
        from src.app.services.market_metrics import cohort_safe_behavior_projection
        behavior = cohort_safe_behavior_projection(db, tenant_id=tenant_id)
        log_trace_event(
            trace_id=trace_id, event_type="market_cohort_behavior", source_type="stage",
            source_id="CohortBehaviorProjection", target_type="cohort",
            target_id="tenant-aggregate", payload=behavior,
        )
    except Exception:
        # An unavailable analytics relation cannot fail a buyer recommendation.
        # Absence remains visible as no recorded cohort projection.
        pass
    return evidence


def operator_product_projection(db, *, sku: str, tenant_id: str = "default") -> Dict[str, Any]:
    """Join the non-sensitive projection to operator-only catalog economics."""
    from src.app.services.catalog_read_model import get_variant
    from src.app.services.supplier_catalog import best_supplier_cost

    key = str(sku or "").strip()
    view = get_variant(db, key, tenant_id=tenant_id)
    if view is None:
        return {"available": False, "sku": key, "reason": "unknown_sku"}
    projection = projections(db, tenant_id=tenant_id, window_days=30).get(key, {})
    cost = best_supplier_cost(
        db, key, tenant_id=tenant_id, currency=str(view.currency or "USD")) or {}
    list_cents = int(view.price_cents) if view.price_cents is not None else None
    wholesale_cents = (
        int(cost["unit_cost_cents"]) if cost.get("unit_cost_cents") is not None else None)
    gross = (
        list_cents - wholesale_cents
        if list_cents is not None and wholesale_cents is not None else None)
    margin_pct = (
        round(gross / float(list_cents), 4) if gross is not None and list_cents else None)
    forecast_units = (
        float(projection["units_per_day"]) * 30.0
        if projection.get("units_per_day") is not None else None
    )
    authorized = bool(
        cost.get("cost_kind") == "validated_landed_quote"
        and not cost.get("simulation_only")
        and cost.get("source_record_id"))
    result = {
        "available": True,
        "tenant_id": tenant_id,
        "sku": key,
        "name": str(getattr(view, "title", "") or key),
        "currency": str(view.currency or "USD"),
        "list_cents": list_cents,
        "wholesale_cents": wholesale_cents,
        "gross_per_unit_cents": gross,
        "gross_margin_pct": margin_pct,
        "forecast_units_30d": round(forecast_units, 2) if forecast_units is not None else None,
        "projected_profit_30d_cents": (
            int(round(gross * forecast_units))
            if gross is not None and forecast_units is not None else None),
        "discount_headroom_cents": None,
        "discount_authorized": authorized,
        "cost_basis": cost.get("cost_kind") or cost.get("cost_basis") or "unavailable",
        "cost_source_system": cost.get("source_system"),
        "cost_source_record_id": cost.get("source_record_id"),
        "cost_provenance_chain": list(cost.get("provenance_chain") or []),
        "simulation_only": bool(cost.get("simulation_only", not authorized)),
        "projection": projection,
    }
    from src.app.services.commercial_action_proposals import product_action_proposals
    result["action_proposals"] = product_action_proposals(
        db, sku=key, tenant_id=tenant_id, operator_projection=result)
    return result
