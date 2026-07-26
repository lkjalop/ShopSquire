"""Pure supplier lifecycle metrics over matched, tenant-scoped events."""
from __future__ import annotations

from statistics import pstdev
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
