"""Pure supplier lifecycle metrics over matched, tenant-scoped events."""
from __future__ import annotations

from statistics import pstdev
from math import exp, sqrt
from typing import Any, Dict, Sequence


def supplier_metrics(
    *, tenant_id: str, supplier_id: str, events: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    scoped = [
        row for row in events
        if str(row.get("tenant_id") or "") == tenant_id
        and str(row.get("supplier_id") or "") == supplier_id
    ]
    quotes = [row for row in scoped if row.get("event_type") == "quote"]
    accepted = [row for row in quotes if row.get("outcome") == "accepted"]
    rejected = [row for row in quotes if row.get("outcome") == "rejected"]
    requested = sum(max(0, int(row.get("requested_qty") or 0)) for row in scoped)
    filled = sum(max(0, int(row.get("filled_qty") or 0)) for row in scoped)
    deliveries = [row for row in scoped if row.get("event_type") == "delivery"]
    on_time_full = [
        row for row in deliveries
        if bool(row.get("on_time")) and int(row.get("filled_qty") or 0) >= int(row.get("requested_qty") or 0)
    ]
    lead_times = [
        max(0.0, float(row["lead_time_days"])) for row in deliveries
        if row.get("lead_time_days") is not None
    ]
    substitutions = [
        row for row in scoped if row.get("event_type") == "substitution"
    ]
    denominator = max(1, len(scoped))
    return {
        "tenant_id": tenant_id,
        "supplier_id": supplier_id,
        "status": "observed" if scoped else "insufficient_data",
        "source_count": len({str(row.get("source_record_id")) for row in scoped
                             if row.get("source_record_id")}),
        "quote_acceptance_rate": len(accepted) / len(quotes) if quotes else None,
        "quote_rejection_rate": len(rejected) / len(quotes) if quotes else None,
        "fill_rate": filled / requested if requested else None,
        "otif_rate": len(on_time_full) / len(deliveries) if deliveries else None,
        "lead_time_mean_days": sum(lead_times) / len(lead_times) if lead_times else None,
        "lead_time_stddev_days": pstdev(lead_times) if len(lead_times) > 1 else (
            0.0 if lead_times else None),
        "substitution_rate": len(substitutions) / denominator,
        "authority": "advisory_metrics_only",
    }


def supplier_shadow_score(
    *,
    tenant_id: str,
    supplier_id: str,
    events: Sequence[Dict[str, Any]],
    minimum_deliveries: int = 5,
    model_version: str = "supplier-shadow-v1",
) -> Dict[str, Any]:
    """Outcome-calibratable score that is never an execution authority."""
    scoped = [
        row for row in events
        if str(row.get("tenant_id") or "") == tenant_id
        and str(row.get("supplier_id") or "") == supplier_id
    ]
    deliveries = [row for row in scoped if row.get("event_type") == "delivery"]
    n = len(deliveries)
    if n < max(1, int(minimum_deliveries)):
        return {
            "tenant_id": tenant_id,
            "supplier_id": supplier_id,
            "model_version": model_version,
            "status": "insufficient_evidence",
            "sample_size": n,
            "minimum_deliveries": int(minimum_deliveries),
            "score": None,
            "execution_allowed": False,
        }
    otif_success = sum(
        bool(row.get("on_time"))
        and int(row.get("filled_qty") or 0) >= int(row.get("requested_qty") or 0)
        for row in deliveries
    )
    otif = otif_success / n
    received = sum(max(0, int(row.get("received_qty") or row.get("filled_qty") or 0)) for row in deliveries)
    rejected = sum(max(0, int(row.get("rejected_qty") or 0)) for row in deliveries)
    quality = max(0.0, 1.0 - (rejected / received)) if received else 0.0
    lead_times = [
        max(0.0, float(row["lead_time_days"]))
        for row in deliveries if row.get("lead_time_days") is not None
    ]
    mean_lead = sum(lead_times) / len(lead_times) if lead_times else 0.0
    spread = pstdev(lead_times) if len(lead_times) > 1 else 0.0
    reliability = exp(-(spread / mean_lead)) if mean_lead > 0 else 0.0
    comparable_prices = [
        float(row["price_index"])
        for row in scoped
        if row.get("price_index") is not None
        and bool(row.get("currency_comparable"))
        and bool(row.get("uom_comparable"))
    ]
    price = (
        max(0.0, min(1.0, 1.0 / max(0.01, sum(comparable_prices) / len(comparable_prices))))
        if comparable_prices else 0.0
    )
    response_hours = [
        max(0.0, float(row["response_hours"]))
        for row in scoped if row.get("event_type") == "quote" and row.get("response_hours") is not None
    ]
    responsiveness = (
        max(0.0, min(1.0, 1.0 - (sum(response_hours) / len(response_hours)) / 168.0))
        if response_hours else 0.0
    )
    components = {
        "otif": otif,
        "quality": quality,
        "reliability": reliability,
        "price": price,
        "responsiveness": responsiveness,
    }
    score = (
        0.35 * otif + 0.25 * quality + 0.20 * reliability
        + 0.10 * price + 0.10 * responsiveness
    )
    low, high = _wilson(otif_success, n)
    outcomes = [
        float(row["realized_outcome"])
        for row in scoped if row.get("realized_outcome") is not None
    ]
    return {
        "tenant_id": tenant_id,
        "supplier_id": supplier_id,
        "model_version": model_version,
        "status": "shadow_observed",
        "sample_size": n,
        "score": round(score, 4),
        "confidence_interval": {"low": round(low, 4), "high": round(high, 4), "basis": "otif_wilson_95"},
        "components": {key: round(value, 4) for key, value in components.items()},
        "outcome_calibration": {
            "status": "available" if outcomes else "awaiting_realized_outcomes",
            "observations": len(outcomes),
            "mean_realized_outcome": round(sum(outcomes) / len(outcomes), 4) if outcomes else None,
        },
        "execution_allowed": False,
        "authority": "shadow_only",
    }


def _wilson(successes: int, total: int) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    z = 1.96
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)
