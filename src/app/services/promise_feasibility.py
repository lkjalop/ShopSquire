"""Deterministic quantity-by-deadline feasibility over normalized supply lines."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


def _instant(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_aware_promise_instant_required")
    return parsed.astimezone(timezone.utc)


def evaluate_promise_feasibility(
    *, requested_quantity: int, requested_arrival_at: datetime | str,
    evaluated_at: datetime | str, supply_lines: Iterable[dict[str, Any]],
    dependency_versions: dict[str, str],
    latest_viable_response_at: datetime | str | None = None,
) -> dict[str, Any]:
    requested = int(requested_quantity)
    if requested <= 0:
        raise ValueError("requested_quantity_must_be_positive")
    deadline = _instant(requested_arrival_at)
    evaluated = _instant(evaluated_at)
    latest_response = _instant(latest_viable_response_at)
    assert deadline is not None and evaluated is not None
    confirmed = 0
    uncertain = 0
    unavailable_or_late = 0
    reasons: list[str] = []
    normalized: list[dict[str, Any]] = []
    for raw in supply_lines:
        quantity = max(0, int(raw.get("quantity") or 0))
        if quantity == 0:
            continue
        status = str(raw.get("status") or "unknown").lower()
        arrival_min = _instant(raw.get("arrival_min"))
        arrival_max = _instant(raw.get("arrival_max"))
        normalized.append({
            "source_ref": str(raw.get("source_ref") or "unknown"), "quantity": quantity,
            "status": status,
            "arrival_min": arrival_min.isoformat() if arrival_min else None,
            "arrival_max": arrival_max.isoformat() if arrival_max else None,
            "authority": str(raw.get("authority") or "unknown"),
        })
        if status in {"rejected", "cancelled", "unavailable"}:
            unavailable_or_late += quantity
            continue
        if arrival_max is None:
            uncertain += quantity
            reasons.append("arrival_evidence_missing")
            continue
        if arrival_max > deadline:
            if status == "confirmed" and arrival_min is not None and arrival_min <= deadline:
                uncertain += quantity
                reasons.append("arrival_range_crosses_deadline")
            else:
                unavailable_or_late += quantity
                reasons.append("arrival_after_deadline")
            continue
        if status == "confirmed":
            confirmed += quantity
        else:
            uncertain += quantity
            reasons.append("supply_confirmation_required")
    latest_elapsed = latest_response is not None and evaluated > latest_response
    if latest_elapsed and confirmed < requested:
        feasibility = "missed"
        reasons.append("latest_viable_response_elapsed")
    elif confirmed >= requested:
        feasibility = "met"
    elif confirmed + uncertain < requested:
        feasibility = "missed"
        reasons.append("insufficient_quantity_by_deadline")
    else:
        feasibility = "unknown"
    reasons = list(dict.fromkeys(reasons))
    return {
        "calculation_version": "promise-feasibility-v1",
        "feasibility": feasibility,
        "requested_quantity": requested,
        "requested_arrival_at": deadline.isoformat(),
        "evaluated_at": evaluated.isoformat(),
        "latest_viable_response_at": latest_response.isoformat() if latest_response else None,
        "quantity_confirmed_by_deadline": min(requested, confirmed),
        "unknown_quantity": min(requested, uncertain),
        "late_or_unavailable_quantity": unavailable_or_late,
        "remaining_quantity": max(0, requested - confirmed),
        "reason_codes": reasons,
        "state_prevented": None if feasibility == "met" else "unsupported_full_delivery_promise",
        "dependency_versions": {str(key): str(value) for key, value in sorted(dependency_versions.items())},
        "supply_lines": normalized,
        "authority": "deterministic_calculation",
    }


def evaluate_critical_path(
    *, requested_quantity: int, requested_arrival_at: datetime | str,
    evaluated_at: datetime | str, supply_lines: Iterable[dict[str, Any]],
    dependency_versions: dict[str, str], response_expectation: dict[str, Any],
    stage_duration_seconds: dict[str, tuple[int, int]],
    carrier_cutoff_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Evaluate the complete post-response path without inventing missing clocks.

    Adapters normalize warehouse/carrier-specific facts into bounded stage ranges; the
    core remains product-, provider-, and country-agnostic.
    """
    base = evaluate_promise_feasibility(
        requested_quantity=requested_quantity, requested_arrival_at=requested_arrival_at,
        evaluated_at=evaluated_at, supply_lines=supply_lines,
        dependency_versions=dependency_versions,
    )
    failed = list(base["reason_codes"])
    required = ("operator_authorization", "allocation_confirmation", "dispatch_preparation",
                "transit", "inspection_or_cross_dock", "final_mile")
    invalid_stages = [name for name in required if name not in stage_duration_seconds]
    if invalid_stages:
        failed.append("critical_path_stage_missing")
    response_due = _instant(response_expectation.get("quote_due_at"))
    if response_expectation.get("calendar_state") == "unknown" or response_due is None:
        failed.append("supplier_response_expectation_unknown")
    low_seconds = 0
    high_seconds = 0
    for name in required:
        bounds = stage_duration_seconds.get(name)
        if bounds is None:
            continue
        low, high = int(bounds[0]), int(bounds[1])
        if low < 0 or high < low:
            raise ValueError(f"invalid_stage_duration:{name}")
        low_seconds += low
        high_seconds += high
    deadline = _instant(requested_arrival_at)
    assert deadline is not None
    earliest = response_due + timedelta(seconds=low_seconds) if response_due else None
    latest = response_due + timedelta(seconds=high_seconds) if response_due else None
    latest_viable_response = deadline - timedelta(seconds=high_seconds) if not invalid_stages else None
    cutoff = _instant(carrier_cutoff_at)
    dispatch_ready = None
    if response_due:
        pre_dispatch = sum(
            int(stage_duration_seconds.get(name, (0, 0))[1])
            for name in ("operator_authorization", "allocation_confirmation", "dispatch_preparation")
        )
        dispatch_ready = response_due + timedelta(seconds=pre_dispatch)
    if cutoff is not None and (dispatch_ready is None or dispatch_ready > cutoff):
        failed.append("carrier_cutoff_missed")
    if latest is not None and latest > deadline:
        failed.append("critical_path_arrival_after_deadline")
    failed = list(dict.fromkeys(failed))
    if "carrier_cutoff_missed" in failed or "critical_path_arrival_after_deadline" in failed:
        feasibility = "missed"
    elif invalid_stages or response_due is None or base["feasibility"] == "unknown":
        feasibility = "unknown"
    else:
        feasibility = base["feasibility"]
    return {
        **base,
        "calculation_version": "promise-critical-path-v1",
        "feasibility": feasibility,
        "quantity_by_deadline": base["quantity_confirmed_by_deadline"] if feasibility != "missed" else 0,
        "earliest_arrival_range": {
            "earliest": earliest.isoformat() if earliest else None,
            "latest": latest.isoformat() if latest else None,
        },
        "latest_viable_supplier_response_at": (
            latest_viable_response.isoformat() if latest_viable_response else None
        ),
        "carrier_cutoff_at": cutoff.isoformat() if cutoff else None,
        "dispatch_ready_at": dispatch_ready.isoformat() if dispatch_ready else None,
        "failed_constraints": failed,
        "reason_codes": failed,
        "response_expectation": response_expectation,
    }
