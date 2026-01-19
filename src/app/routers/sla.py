import os
from typing import Dict
from fastapi import APIRouter
from prometheus_client import generate_latest, REGISTRY

router = APIRouter(prefix="/api/v1/sla", tags=["sla"])


def _parse_total(metric_prefix: str, body: str) -> float:
    total = 0.0
    for line in body.splitlines():
        if line.startswith(metric_prefix):
            try:
                val = float(line.split()[-1])
                total += val
            except Exception:
                pass
    return total


@router.get("/summary")
def summary() -> Dict:
    # Parse current metrics text to compute basic aggregates
    body = generate_latest(REGISTRY).decode("utf-8", errors="ignore")
    incidents = _parse_total("shopsquire_incident_alerts_total", body)
    tickets = _parse_total("shopsquire_tickets_created_total", body)
    chaos = _parse_total("shopsquire_chaos_injected_total", body)
    latency_count = _parse_total("shopsquire_pricing_latency_seconds_count", body)
    latency_sum = _parse_total("shopsquire_pricing_latency_seconds_sum", body)
    avg_latency = (latency_sum / latency_count) if latency_count > 0 else 0.0
    return {
        "incidents_total": incidents,
        "tickets_total": tickets,
        "chaos_total": chaos,
        "pricing_latency_avg_sec": avg_latency,
    }
