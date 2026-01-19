from typing import Optional
from fastapi import APIRouter
from fastapi.responses import Response
from prometheus_client import Counter, Histogram, generate_latest, REGISTRY

incident_alerts_total = Counter(
    "shopsquire_incident_alerts_total",
    "Incident alerts emitted",
    labelnames=["topic", "severity"],
)

tickets_created_total = Counter(
    "shopsquire_tickets_created_total",
    "Tickets created",
    labelnames=["topic", "priority"],
)

pricing_latency_seconds = Histogram(
    "shopsquire_pricing_latency_seconds",
    "Latency of pricing suggest endpoint",
)

chaos_injected_total = Counter(
    "shopsquire_chaos_injected_total",
    "Chaos latency injections",
    labelnames=["latency_ms"],
)


def record_incident_alert(topic: str, severity: str):
    incident_alerts_total.labels(topic=topic, severity=severity).inc()


def record_ticket(topic: str, priority: str):
    tickets_created_total.labels(topic=topic, priority=priority).inc()


def record_pricing_latency(seconds: float):
    pricing_latency_seconds.observe(seconds)


router = APIRouter(prefix="", tags=["metrics"])


@router.get("/metrics")
def metrics() -> Response:
    content = generate_latest(REGISTRY)
    return Response(content, media_type="text/plain; version=0.0.4; charset=utf-8")
