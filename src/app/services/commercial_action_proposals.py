"""Governed commercial proposals.

Detectors and models may surface an opportunity. These functions only construct
bounded proposals after deterministic policy checks. They never change a price,
send a supplier message, or create a purchase order.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

from sqlalchemy import text

from src.app.services.fulfillment.economics import compute
from src.app.services.market_action_policy import authorize_replenishment


def propose_surplus_discount(
    *,
    sku: str,
    projection: Dict[str, Any],
    economics: Dict[str, Any],
    floor_margin_pct: float = 0.10,
    surplus_dsi_days: float = 90.0,
) -> Dict[str, Any]:
    """Propose a bounded discount; validated landed cost is mandatory."""
    dsi = _float(projection.get("dsi_days"))
    surplus = bool(projection.get("dead_stock")) or (
        dsi is not None and dsi >= float(surplus_dsi_days)
    )
    authorized_cost = bool(
        economics.get("discount_authorized")
        and economics.get("cost_basis") == "validated_landed_supplier_quote"
        and not economics.get("simulation_only")
    )
    deal = compute(
        supplier_unit_cost_cents=economics.get("wholesale_cents"),
        retail_unit_cents=economics.get("list_cents"),
        quantity=1,
        floor_margin_pct=floor_margin_pct,
    )
    reasons: list[str] = []
    if not surplus:
        reasons.append("not_surplus_or_low_velocity")
    if not authorized_cost:
        reasons.append("unvalidated_landed_cost")
    if deal is None:
        reasons.append("missing_price_or_cost")
    elif not deal.clears_floor:
        reasons.append("below_margin_floor")

    max_discount = int(deal.max_buyer_discount_cents) if deal and authorized_cost else 0
    # Keep half the validated headroom and never propose more than 10% of list.
    list_cents = int(economics.get("list_cents") or 0)
    recommended = min(max_discount // 2, int(round(list_cents * 0.10)))
    eligible = not reasons and recommended > 0
    if not eligible:
        recommended = 0
    discounted_retail = max(0, list_cents - recommended)
    landed = int(economics.get("wholesale_cents") or 0)
    margin_after = (
        round((discounted_retail - landed) / discounted_retail, 4)
        if discounted_retail > 0 and landed > 0 else None
    )
    return {
        "action_type": "surplus_discount",
        "sku": str(sku),
        "eligible": eligible,
        "reasons": reasons,
        "surplus": surplus,
        "velocity_dsi_days": dsi,
        "max_discount_cents": max_discount,
        "recommended_discount_cents": recommended,
        "recommended_discount_pct": (
            round(recommended / list_cents, 4) if list_cents > 0 else 0.0
        ),
        "margin_after_pct": margin_after,
        "currency": str(economics.get("currency") or ""),
        "human_gate": "required" if eligible else "blocked",
        "auto_applied": False,
    }


def propose_replenishment(
    *,
    sku: str,
    tenant_id: str,
    currency: str,
    demand_facts: Iterable[Dict[str, Any]],
    atp: Dict[str, Any],
    economics: Dict[str, Any],
    now: datetime | None = None,
    forecast_quality: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    verdict = authorize_replenishment(
        demand_facts=demand_facts,
        atp=atp,
        economics=economics,
        now=now,
        tenant_id=tenant_id,
        sku=sku,
        currency=currency,
        forecast_quality=forecast_quality,
    )
    authorized = bool(verdict.get("allowed"))
    return {
        "action_type": "replenishment",
        "sku": str(sku),
        "authorized": authorized,
        "reasons": list(verdict.get("reasons") or []),
        "shortfall": int(verdict.get("shortfall") or 0),
        "lead_time_days": verdict.get("lead_time_days"),
        "demand_source_count": int(verdict.get("demand_source_count") or 0),
        "qualified_demand_facts": int(verdict.get("qualified_demand_facts") or 0),
        "economics_verdict": (
            "validated" if verdict.get("economics_authoritative") else "unverified"
        ),
        "send_gate": "human" if authorized else "blocked",
        "auto_sent": False,
        "authority": "operator_advisory_only",
        "forecast_quality_shadow": verdict.get("forecast_quality_shadow"),
    }


def product_action_proposals(
    db,
    *,
    sku: str,
    tenant_id: str,
    operator_projection: Dict[str, Any],
    now: datetime | None = None,
) -> Dict[str, Any]:
    """Assemble action previews from canonical facts for one tenant/SKU."""
    currency = str(operator_projection.get("currency") or "").upper()
    demand_facts = _demand_growth_facts(db, tenant_id=tenant_id, sku=sku, now=now)
    atp = _latest_atp_deficit(db, tenant_id=tenant_id, sku=sku)
    economics = _policy_economics(operator_projection, tenant_id=tenant_id, sku=sku)
    forecast_quality = _latest_forecast_quality(db, tenant_id=tenant_id, sku=sku)
    return {
        "discount": propose_surplus_discount(
            sku=sku,
            projection=operator_projection.get("projection") or {},
            economics=operator_projection,
        ),
        "replenishment": propose_replenishment(
            sku=sku,
            tenant_id=tenant_id,
            currency=currency,
            demand_facts=demand_facts,
            atp=atp,
            economics=economics,
            now=now,
            forecast_quality=forecast_quality,
        ),
    }


def _latest_forecast_quality(db, *, tenant_id: str, sku: str) -> Dict[str, Any]:
    try:
        rows = db.execute(text("""
            SELECT metric_name, value_numeric, coverage, status, as_of
            FROM executive_metric_snapshot
            WHERE tenant_id=:tenant AND subject_type='sku' AND subject_id=:sku
              AND metric_name IN ('forecast_wape','forecast_coverage')
            ORDER BY as_of DESC
        """), {"tenant": tenant_id, "sku": sku}).fetchall()
    except Exception:
        return {"status": "unavailable", "reason": "metric_snapshot_unavailable"}
    values: Dict[str, Any] = {}
    status = "unavailable"
    for name, value, coverage, row_status, _as_of in rows:
        if str(name) in values:
            continue
        values[str(name)] = float(value) if value is not None else None
        values[f"{name}_coverage"] = float(coverage or 0.0)
        status = str(row_status or status)
    return {
        "status": status,
        "wape": values.get("forecast_wape"),
        "coverage": (
            values.get("forecast_coverage")
            if values.get("forecast_coverage") is not None
            else values.get("forecast_wape_coverage", 0.0)),
    }


def _demand_growth_facts(
    db, *, tenant_id: str, sku: str, now: datetime | None = None
) -> list[Dict[str, Any]]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        rows = db.execute(text("""
            SELECT source_system, event_type, quantity, occurred_at, source_record_id,
                   provenance_json, confidence
            FROM marketing_event_fact
            WHERE tenant_id=:tenant AND sku=:sku AND status='active'
        """), {"tenant": tenant_id, "sku": sku}).fetchall()
    except Exception:
        return []
    by_source: Dict[str, Dict[str, Any]] = {}
    positive = {"view_item", "select_item", "add_to_cart", "purchase"}
    for source, event_type, quantity, occurred_at, record_id, provenance, confidence in rows:
        if str(event_type) not in positive:
            continue
        observed = _time(occurred_at)
        if observed is None:
            continue
        age_days = (current - observed).total_seconds() / 86400.0
        if age_days < -1 or age_days > 60:
            continue
        bucket = by_source.setdefault(str(source), {
            "current": 0, "prior": 0, "observed_at": observed,
            "source_record_id": record_id, "provenance": _json_list(provenance),
            "confidence": float(confidence or 0.0),
        })
        units = max(1, int(quantity or 1))
        bucket["current" if age_days <= 30 else "prior"] += units
        if observed >= bucket["observed_at"]:
            bucket.update({
                "observed_at": observed,
                "source_record_id": record_id,
                "provenance": _json_list(provenance),
                "confidence": float(confidence or 0.0),
            })
    facts = []
    for source, bucket in by_source.items():
        current_units = int(bucket["current"])
        prior_units = int(bucket["prior"])
        if current_units <= prior_units or current_units <= 0:
            continue
        facts.append({
            "scope": "this_item",
            "direction": "up",
            "summary": f"30-day demand increased from {prior_units} to {current_units}",
            "confidence": bucket["confidence"],
            "observed_at": bucket["observed_at"].isoformat(),
            "source_system": source,
            "source_record_id": bucket["source_record_id"],
            "provenance_chain": bucket["provenance"],
            "tenant_id": tenant_id,
            "sku": sku,
        })
    return facts


def _latest_atp_deficit(db, *, tenant_id: str, sku: str) -> Dict[str, Any]:
    try:
        row = db.execute(text("""
            SELECT requested_quantity, confirmed_quantity, on_hand_quantity,
                   committed_quantity, incoming_receipts_quantity, lead_time_days,
                   confidence, observed_at, source_system, source_record_id,
                   provenance_json
            FROM inventory_atp_fact
            WHERE tenant_id=:tenant AND sku=:sku AND status='active'
              AND requested_quantity IS NOT NULL
            ORDER BY observed_at DESC LIMIT 1
        """), {"tenant": tenant_id, "sku": sku}).fetchone()
    except Exception:
        row = None
    if not row:
        return {}
    requested = int(row[0] or 0)
    confirmed = int(row[1] or 0)
    return {
        "shortfall": max(0, requested - confirmed),
        "lead_time_days": _float(row[5]),
        "confidence": float(row[6] or 0.0),
        "observed_at": row[7],
        "source_system": row[8],
        "source_record_id": row[9],
        "provenance_chain": _json_list(row[10]),
        "tenant_id": tenant_id,
        "sku": sku,
    }


def _policy_economics(
    projection: Dict[str, Any], *, tenant_id: str, sku: str
) -> Dict[str, Any]:
    list_cents = int(projection.get("list_cents") or 0)
    wholesale_cents = int(projection.get("wholesale_cents") or 0)
    margin = (
        (list_cents - wholesale_cents) / list_cents
        if list_cents > 0 and wholesale_cents > 0 else 0.0
    )
    return {
        "available": bool(list_cents and wholesale_cents),
        "clears_floor": margin >= 0.10,
        "cost_basis": projection.get("cost_basis"),
        "source_record_id": projection.get("cost_source_record_id"),
        "provenance_chain": projection.get("cost_provenance_chain") or [],
        "tenant_id": tenant_id,
        "sku": sku,
        "currency": projection.get("currency"),
    }


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(value or "[]") if isinstance(value, str) else value
    except (TypeError, ValueError):
        parsed = []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None
