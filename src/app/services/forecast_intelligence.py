"""Comparable, shadow-only forecast intelligence from reconciled purchase history."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.demand_forecast import (
    _croston_sba_one,
    _ewma_one,
    _tsb_one,
    rolling_origin_evaluation,
)


COMPUTATION_VERSION = "forecast_intelligence_v1"


def _daily_series(rows: list[Any], *, lookback_days: int, as_of: date) -> tuple[list[float], list[str]]:
    start = as_of - timedelta(days=max(1, int(lookback_days)) - 1)
    by_day: dict[str, float] = {}
    sources: set[str] = set()
    for row in rows:
        day = str(row[0] or "")[:10]
        if not day:
            continue
        by_day[day] = by_day.get(day, 0.0) + max(0.0, float(row[1] or 0.0))
        if len(row) > 2 and row[2]:
            sources.add(str(row[2]))
    values = [
        by_day.get((start + timedelta(days=offset)).isoformat(), 0.0)
        for offset in range((as_of - start).days + 1)
    ]
    return values, sorted(sources)


def abc_xyz_segments(
    histories: dict[str, list[float]],
    annual_values: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Classify value contribution (ABC) and demand variability (XYZ)."""
    values = annual_values or {
        sku: sum(max(0.0, float(value)) for value in history)
        for sku, history in histories.items()
    }
    total = sum(max(0.0, value) for value in values.values())
    ranked = sorted(values, key=lambda sku: (-max(0.0, values[sku]), sku))
    cumulative = 0.0
    abc: dict[str, str] = {}
    for sku in ranked:
        share_before = cumulative / total if total > 0 else 0.0
        abc[sku] = "A" if share_before < 0.8 else "B" if share_before < 0.95 else "C"
        cumulative += max(0.0, values[sku])

    result: dict[str, dict[str, Any]] = {}
    for sku, history in histories.items():
        clean = [max(0.0, float(value)) for value in history]
        mean = statistics.fmean(clean) if clean else 0.0
        if len(clean) < 28 or mean <= 0:
            xyz = "undefined"
            coefficient = None
            status = "insufficient_history" if len(clean) < 28 else "undefined_zero_mean"
        else:
            coefficient = statistics.pstdev(clean) / mean
            xyz = "X" if coefficient <= 0.5 else "Y" if coefficient <= 1.0 else "Z"
            status = "observed"
        result[sku] = {
            "abc_class": abc.get(sku, "undefined") if total > 0 else "undefined",
            "abc_status": "observed" if total > 0 else "undefined_zero_value",
            "abc_value": round(values.get(sku, 0.0), 4),
            "xyz_class": xyz,
            "xyz_status": status,
            "coefficient_of_variation": (
                round(coefficient, 6) if coefficient is not None else None
            ),
            "history_points": len(clean),
        }
    return result


def compare_forecast_models(
    history: list[float],
    *,
    lead_time_days: float,
    segmentation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    horizon_days = max(1, min(365, int(math.ceil(float(lead_time_days or 1.0)))))
    clean = [max(0.0, float(value)) for value in history]
    evaluation = rolling_origin_evaluation(clean, horizon_days=horizon_days)
    if clean:
        candidates = {
            "seasonal_naive": clean[-7] if len(clean) >= 7 else clean[-1],
            "ewma": _ewma_one(clean),
            "croston_sba": _croston_sba_one(clean),
            "tsb": _tsb_one(clean),
        }
    else:
        candidates = {
            "seasonal_naive": None,
            "ewma": None,
            "croston_sba": None,
            "tsb": None,
        }
    model_rows: dict[str, Any] = {}
    for model, daily in candidates.items():
        metrics = evaluation.get("models", {}).get(model, {})
        model_rows[model] = {
            "status": metrics.get("status", evaluation.get("status", "undefined")),
            "daily_units": round(daily, 6) if daily is not None else None,
            "horizon_units": round(daily * horizon_days, 4) if daily is not None else None,
            "wape": metrics.get("wape"),
            "wape_status": metrics.get("wape_status", "undefined"),
            "mase": metrics.get("mase"),
            "mase_status": metrics.get("mase_status", "undefined"),
            "bias": metrics.get("bias"),
            "origins": metrics.get("origins", 0),
            "evaluation_horizon_days": horizon_days,
        }
    selected = evaluation.get("winner")
    if selected not in model_rows:
        selected = None
    demand_mean = statistics.fmean(clean) if clean else None
    demand_variance = statistics.pvariance(clean) if len(clean) >= 2 else None
    lead_time_windows = [
        sum(clean[index:index + horizon_days])
        for index in range(0, len(clean) - horizon_days + 1)
    ]
    sorted_windows = sorted(lead_time_windows)

    def percentile(probability: float) -> float | None:
        if not sorted_windows:
            return None
        position = max(0, min(len(sorted_windows) - 1, math.ceil(
            probability * len(sorted_windows),
        ) - 1))
        return round(float(sorted_windows[position]), 4)

    return {
        "status": evaluation.get("status", "undefined"),
        "selected_model": selected,
        "horizon": {
            "kind": "supplier_lead_time",
            "days": horizon_days,
            "input_days": float(lead_time_days or 1.0),
        },
        "history_points": len(clean),
        "origins": evaluation.get("origins", 0),
        "evaluation": {
            "kind": evaluation.get("kind", "rolling_origin_lead_time_demand"),
            "horizon_days": evaluation.get("horizon_days", horizon_days),
            "status": evaluation.get("status", "undefined"),
        },
        "demand_distribution": {
            "kind": "empirical_daily",
            "mean_daily": round(demand_mean, 6) if demand_mean is not None else None,
            "variance_daily": (
                round(demand_variance, 6) if demand_variance is not None else None
            ),
            "status": (
                "observed"
                if len(clean) >= 2
                else "insufficient_history"
            ),
            "lead_time_empirical": {
                "status": "observed" if lead_time_windows else "insufficient_history",
                "windows": len(lead_time_windows),
                "mean_units": (
                    round(statistics.fmean(lead_time_windows), 4)
                    if lead_time_windows else None
                ),
                "variance_units2": (
                    round(statistics.pvariance(lead_time_windows), 4)
                    if len(lead_time_windows) >= 2 else None
                ),
                "p50_units": percentile(0.50),
                "p90_units": percentile(0.90),
                "p95_units": percentile(0.95),
            },
        },
        "models": model_rows,
        "segmentation": segmentation or {
            "abc_class": "undefined",
            "xyz_class": "undefined",
        },
        "authority": "shadow_evaluation_only",
        "can_increase_autonomy": False,
    }


def _load_histories(
    *,
    tenant_id: str,
    target_sku: str,
    lookback_days: int,
    as_of: date,
) -> tuple[dict[str, list[float]], dict[str, float], dict[str, Any]]:
    cutoff = as_of - timedelta(days=max(28, int(lookback_days)) - 1)
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT occurred_at, quantity, source_system, sku, value
                FROM marketing_event_fact
                WHERE tenant_id=:tenant AND event_type='purchase'
                  AND status='active' AND occurred_at >= :cutoff
                  AND occurred_at < :end_date AND sku IS NOT NULL
                ORDER BY occurred_at ASC
                """
            ),
            {
                "tenant": tenant_id,
                "cutoff": cutoff.isoformat(),
                "end_date": (as_of + timedelta(days=1)).isoformat(),
            },
        ).fetchall()
    grouped: dict[str, list[Any]] = {}
    annual_values: dict[str, float] = {}
    watermark = None
    source_set: set[str] = set()
    for row in rows:
        sku = str(row[3] or "").strip()
        if not sku:
            continue
        grouped.setdefault(sku, []).append((row[0], row[1], row[2]))
        annual_values[sku] = annual_values.get(sku, 0.0) + max(
            0.0, float(row[4] if row[4] is not None else row[1] or 0.0)
        )
        watermark = max(str(watermark or ""), str(row[0] or "")) or watermark
        if row[2]:
            source_set.add(str(row[2]))
    grouped.setdefault(target_sku, [])
    histories = {
        sku: _daily_series(items, lookback_days=lookback_days, as_of=as_of)[0]
        for sku, items in grouped.items()
    }
    return histories, annual_values, {
        "watermark": watermark,
        "sources": sorted(source_set),
        "row_count": len(rows),
        "status": "available" if rows else "no_data",
    }


def evaluate_inventory_forecast(
    *,
    tenant_id: str,
    sku: str,
    lead_time_days: float,
    lookback_days: int = 180,
    as_of: date | None = None,
    materialize: bool = False,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    item = str(sku or "").strip()
    if not tenant or not item:
        raise ValueError("forecast_intelligence_scope_required")
    evaluation_date = as_of or datetime.now(timezone.utc).date()
    histories, annual_values, source = _load_histories(
        tenant_id=tenant,
        target_sku=item,
        lookback_days=max(28, min(730, int(lookback_days))),
        as_of=evaluation_date,
    )
    segmentation = abc_xyz_segments(histories, annual_values).get(item, {})
    result = compare_forecast_models(
        histories[item],
        lead_time_days=lead_time_days,
        segmentation=segmentation,
    )
    result.update(
        {
            "tenant_id": tenant,
            "sku": item,
            "as_of_date": evaluation_date.isoformat(),
            "source": {
                **source,
                "kind": "reconciled_active_purchase_facts",
                "lookback_days": max(28, min(730, int(lookback_days))),
            },
            "computation_version": COMPUTATION_VERSION,
            "materialized": False,
        }
    )
    if not materialize:
        return result
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    source_watermark = str(source.get("watermark") or "no-data")
    run_id = hashlib.sha256(
        (
            f"{tenant}|{item}|{evaluation_date.isoformat()}|"
            f"{result['horizon']['days']}|{source_watermark}|{COMPUTATION_VERSION}"
        ).encode()
    ).hexdigest()
    with db_session() as db:
        exists = db.execute(
            text("SELECT 1 FROM forecast_intelligence_evaluation WHERE id=:id"),
            {"id": run_id},
        ).fetchone()
        if not exists:
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                text(
                    """
                    INSERT INTO forecast_intelligence_evaluation
                    (id, tenant_id, sku, as_of_date, horizon_kind, horizon_days,
                     history_start, history_end, source_watermark, status,
                     selected_model, abc_class, xyz_class, evaluation_json,
                     computation_version, authority, created_at)
                    VALUES
                    (:id, :tenant, :sku, :as_of, 'supplier_lead_time', :horizon,
                     :history_start, :history_end, :watermark, :status,
                     :selected, :abc, :xyz, :evaluation, :version,
                     'shadow_evaluation_only', :created)
                    """
                ),
                {
                    "id": run_id,
                    "tenant": tenant,
                    "sku": item,
                    "as_of": evaluation_date.isoformat(),
                    "horizon": result["horizon"]["days"],
                    "history_start": (
                        evaluation_date - timedelta(days=len(histories[item]) - 1)
                    ).isoformat(),
                    "history_end": evaluation_date.isoformat(),
                    "watermark": source_watermark,
                    "status": result["status"],
                    "selected": result["selected_model"],
                    "abc": segmentation.get("abc_class"),
                    "xyz": segmentation.get("xyz_class"),
                    "evaluation": encoded,
                    "version": COMPUTATION_VERSION,
                    "created": now,
                },
            )
            db.commit()
    result["materialized"] = True
    result["evaluation_id"] = run_id
    result["duplicate"] = bool(exists)
    return result
