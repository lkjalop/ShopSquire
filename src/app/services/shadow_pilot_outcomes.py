"""Tenant/window outcome scorecard for replay and design-partner shadow pilots.

This composes existing governed metric contracts. It does not turn synthetic
or incomplete measurements into business-lift claims or execution authority.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from src.app.schemas.metric_evidence import MetricEvidence
from src.app.services.advanced_inventory_intelligence import (
    estimate_lost_demand,
    forecast_value_added,
)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _tenant_rows(rows: Iterable[dict[str, Any]], tenant_id: str) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if str(row.get("tenant_id") or "") == tenant_id
    ]


def measure_shadow_pilot_outcomes(
    *,
    tenant_id: str,
    window_start: str,
    window_end: str,
    forecast_pairs: Iterable[dict[str, Any]],
    demand_rows: Iterable[dict[str, Any]],
    gross_margin_evidence: dict[str, Any] | None,
    gmroi_evidence: MetricEvidence | None,
    attribution_events: Iterable[dict[str, Any]],
    operator_events: Iterable[dict[str, Any]],
    simulation_only: bool,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    start, end = _utc(window_start), _utc(window_end)
    if not tenant or end <= start:
        raise ValueError("shadow_pilot_measurement_scope_required")

    forecasts = _tenant_rows(forecast_pairs, tenant)
    comparable = [
        row for row in forecasts
        if row.get("baseline_error") is not None
        and row.get("candidate_error") is not None
    ]
    if comparable:
        baseline = sum(float(row["baseline_error"]) for row in comparable) / len(comparable)
        candidate = sum(float(row["candidate_error"]) for row in comparable) / len(comparable)
        metric_names = {str(row.get("metric") or "") for row in comparable}
        metric = next(iter(metric_names)) if len(metric_names) == 1 else "mixed_incomparable"
        fva = (
            forecast_value_added(
                baseline_error=baseline,
                candidate_error=candidate,
                metric=metric,
            )
            if len(metric_names) == 1
            else {
                "status": "undefined_incomparable_metrics",
                "metric": metric,
                "value": None,
                "authority": "shadow_only",
                "execution_allowed": False,
            }
        )
        fva["source_records"] = sorted({
            str(row.get("source_record_id"))
            for row in comparable if row.get("source_record_id")
        })
    else:
        fva = {
            "status": "undefined_missing_comparable_errors",
            "metric": None,
            "value": None,
            "authority": "shadow_only",
            "execution_allowed": False,
            "source_records": [],
        }

    demand = _tenant_rows(demand_rows, tenant)
    lost = estimate_lost_demand(demand)
    stockouts = {
        **lost,
        "stockout_days": (
            sum(1 for row in demand if bool(row.get("stockout")))
            if demand else None
        ),
        "source_records": sorted({
            str(row.get("source_record_id"))
            for row in demand if row.get("source_record_id")
        }),
    }

    margin = gross_margin_evidence or {}
    margin_valid = (
        str(margin.get("tenant_id") or "") == tenant
        and margin.get("value_minor") is not None
        and bool(margin.get("currency"))
        and bool(margin.get("source_records"))
    )
    margin_out = {
        "status": "observed" if margin_valid else "unavailable",
        "value_minor": margin.get("value_minor") if margin_valid else None,
        "currency": str(margin.get("currency")).upper() if margin_valid else None,
        "source_records": list(margin.get("source_records") or []) if margin_valid else [],
        "reason": None if margin_valid else "governed_gross_margin_evidence_required",
    }

    gmroi_valid = (
        gmroi_evidence is not None
        and gmroi_evidence.tenant_id == tenant
        and gmroi_evidence.status == "observed"
    )
    gmroi_out = (
        gmroi_evidence.model_dump(mode="json")
        if gmroi_valid else {
            "status": "unavailable",
            "value": None,
            "reason": "authoritative_gmroi_evidence_required",
        }
    )

    attribution = _tenant_rows(attribution_events, tenant)
    eligible = [row for row in attribution if bool(row.get("eligible"))]
    late = sum(1 for row in eligible if bool(row.get("late")))
    credited = sum(
        1 for row in eligible
        if bool(row.get("attributed")) and not bool(row.get("late"))
    )
    attribution_out = {
        "status": "observed" if eligible else "insufficient_data",
        "eligible_outcomes": len(eligible),
        "credited_outcomes": credited,
        "late_outcomes_excluded": late,
        "coverage": round(credited / len(eligible), 6) if eligible else None,
    }

    workload = _tenant_rows(operator_events, tenant)
    reviews = sum(
        1 for row in workload if row.get("event_type") == "proposal_reviewed"
    )
    approvals = sum(
        1 for row in workload if row.get("event_type") == "proposal_approved"
    )
    overrides = sum(
        1 for row in workload if row.get("event_type") == "proposal_overridden"
    )
    resolved = approvals + overrides
    workload_out = {
        "status": "observed" if workload else "insufficient_data",
        "reviewed": reviews,
        "approved": approvals,
        "overridden": overrides,
        "human_minutes": (
            round(sum(float(row.get("duration_seconds") or 0) for row in workload) / 60, 6)
            if workload else None
        ),
        "approval_rate": round(approvals / resolved, 6) if resolved else None,
        "override_rate": round(overrides / resolved, 6) if resolved else None,
    }

    return {
        "tenant_id": tenant,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "forecast_value_added": fva,
        "stockouts": stockouts,
        "gross_margin": margin_out,
        "gmroi": gmroi_out,
        "attribution": attribution_out,
        "operator_workload": workload_out,
        "authority": "simulation_only" if simulation_only else "measurement_only",
        "autonomy_increase_allowed": False,
    }
