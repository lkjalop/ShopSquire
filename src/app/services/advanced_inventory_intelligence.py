"""Bounded inventory intelligence with explicit evidence and authority states.

These calculations describe observations or shadow evaluations. They do not
authorize purchasing, pricing, disposal, or identity changes.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def lot_ageing_report(
    lots: Iterable[dict[str, Any]],
    *,
    as_of: str,
) -> dict[str, Any]:
    """Report remaining, expired and near-expiry stock without inventing dates."""
    stamp = _utc(as_of)
    rows: list[dict[str, Any]] = []
    missing_expiry = 0
    for raw in lots:
        quantity = max(0.0, float(raw.get("quantity_remaining") or 0.0))
        expiry_value = raw.get("expires_at")
        expiry = _utc(str(expiry_value)) if expiry_value else None
        days = math.floor((expiry - stamp).total_seconds() / 86400) if expiry else None
        state = (
            "expiry_unknown" if expiry is None
            else "expired" if days < 0
            else "expires_today" if days == 0
            else "near_expiry" if days <= 30
            else "serviceable"
        )
        missing_expiry += int(expiry is None and quantity > 0)
        rows.append({
            "lot_id": str(raw.get("lot_id") or ""),
            "variant_id": str(raw.get("variant_id") or ""),
            "location_id": str(raw.get("location_id") or ""),
            "quantity_remaining": quantity,
            "uom": str(raw.get("uom") or "").upper(),
            "expires_at": expiry.isoformat() if expiry else None,
            "days_to_expiry": days,
            "ageing_state": state,
            "unit_cost_minor": (
                int(raw["unit_cost_minor"])
                if raw.get("unit_cost_minor") is not None else None
            ),
        })
    expired = [row for row in rows if row["ageing_state"] == "expired"]
    known_value = all(row["unit_cost_minor"] is not None for row in expired)
    return {
        "status": "observed" if rows else "undefined_no_lots",
        "as_of": stamp.isoformat(),
        "lots": rows,
        "expired_units": round(sum(row["quantity_remaining"] for row in expired), 6),
        "expired_value_minor": (
            round(sum(
                row["quantity_remaining"] * row["unit_cost_minor"]
                for row in expired
            ))
            if known_value else None
        ),
        "expiry_completeness": {
            "status": "complete" if not missing_expiry else "incomplete",
            "missing_lots": missing_expiry,
        },
        "authority": "observation_only",
        "execution_allowed": False,
    }


def aggregate_uom_quantities(
    rows: Iterable[dict[str, Any]],
    *,
    target_uom: str,
    converter: Callable[[Decimal, str, str, str], Any],
    at_time: str,
) -> dict[str, Any]:
    """Aggregate only quantities supported by governed conversion authority."""
    target = str(target_uom or "").strip().upper()
    total = Decimal("0")
    authorities: set[str] = set()
    incomparable: list[dict[str, str]] = []
    for row in rows:
        source = str(row.get("uom") or "").strip().upper()
        quantity = Decimal(str(row.get("quantity") or 0))
        result = converter(quantity, source, target, at_time)
        if getattr(result, "status", None) != "comparable":
            incomparable.append({
                "from_uom": source,
                "reason": str(getattr(result, "reason", "conversion_unavailable")),
            })
            continue
        total += Decimal(result.value)
        if getattr(result, "authority_id", None):
            authorities.add(str(result.authority_id))
    return {
        "status": "comparable" if not incomparable else "incomparable",
        "quantity": str(total) if not incomparable else None,
        "target_uom": target,
        "conversion_authority_ids": sorted(authorities),
        "incomparable": incomparable,
        "authority": "derived_from_approved_uom",
        "execution_allowed": False,
    }


def estimate_lost_demand(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Separate observed lost demand from censored-sales estimates."""
    records = list(rows)
    if not records:
        return {
            "status": "undefined_no_history",
            "lost_units": None,
            "method": None,
            "authority": "shadow_only",
        }
    if all(row.get("latent_demand_units") is not None for row in records):
        lost = sum(max(
            0.0,
            float(row["latent_demand_units"])
            - float(row.get("fulfilled_units") or row.get("observed_sales_units") or 0),
        ) for row in records)
        return {
            "status": "observed_latent_attempts",
            "lost_units": round(lost, 6),
            "method": "latent_minus_fulfilled",
            "authority": "observation_only",
        }
    uncensored = [
        float(row.get("observed_sales_units") or 0)
        for row in records
        if not bool(row.get("stockout"))
    ]
    censored = [row for row in records if bool(row.get("stockout"))]
    if len(uncensored) < 7 or not censored:
        return {
            "status": "undefined_insufficient_uncensored_history",
            "lost_units": None,
            "method": None,
            "authority": "shadow_only",
        }
    baseline = sum(uncensored) / len(uncensored)
    lost = sum(max(
        0.0, baseline - float(row.get("observed_sales_units") or 0),
    ) for row in censored)
    return {
        "status": "estimated_stockout_censoring",
        "lost_units": round(lost, 6),
        "method": "uncensored_mean_gap",
        "uncertainty": "high",
        "authority": "shadow_only",
    }


def reconcile_hierarchical_forecasts(
    leaf_forecasts: dict[str, float],
    parent_by_node: dict[str, str],
) -> dict[str, Any]:
    """Bottom-up reconciliation: every parent exactly equals its descendants."""
    totals: dict[str, float] = defaultdict(float)
    for leaf, value in leaf_forecasts.items():
        amount = max(0.0, float(value))
        totals[str(leaf)] += amount
        seen = {str(leaf)}
        node = str(leaf)
        while node in parent_by_node:
            node = str(parent_by_node[node])
            if node in seen:
                raise ValueError("forecast_hierarchy_cycle")
            seen.add(node)
            totals[node] += amount
    return {
        "status": "reconciled" if leaf_forecasts else "undefined_no_forecasts",
        "method": "bottom_up",
        "forecasts": {
            key: round(value, 6) for key, value in sorted(totals.items())
        },
        "authority": "shadow_only",
        "execution_allowed": False,
    }


def forecast_value_added(
    *,
    baseline_error: float | None,
    candidate_error: float | None,
    metric: str,
) -> dict[str, Any]:
    """FVA relative to a declared baseline; positive means error reduction."""
    if baseline_error is None or candidate_error is None:
        status = "undefined_missing_comparable_errors"
        value = None
    elif baseline_error <= 0:
        status = "undefined_zero_baseline_error"
        value = None
    else:
        status = "observed"
        value = round((baseline_error - candidate_error) / baseline_error, 6)
    return {
        "status": status,
        "metric": str(metric),
        "value": value,
        "interpretation": "relative_error_reduction" if value is not None else None,
        "authority": "shadow_only",
        "execution_allowed": False,
    }


def spend_weighted_concentration(
    supplier_spend_minor: dict[str, int | float],
) -> dict[str, Any]:
    """HHI over attributable spend, not dependency-link counts."""
    clean = {
        str(key): max(0.0, float(value))
        for key, value in supplier_spend_minor.items()
        if float(value) > 0
    }
    total = sum(clean.values())
    hhi = sum((value / total) ** 2 for value in clean.values()) if total else None
    return {
        "status": "observed" if hhi is not None else "undefined_no_spend",
        "supplier_count": len(clean),
        "attributable_spend_minor": round(total),
        "hhi": round(hhi, 6) if hhi is not None else None,
        "method": "spend_weighted_hhi",
        "authority": "observation_only",
    }
