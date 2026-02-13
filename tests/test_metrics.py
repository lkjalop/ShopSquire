from fastapi.testclient import TestClient
from src.app.main import create_app
from src.app.config import get_settings
import json
from src.app.observability.metrics import record_parallel_cache_event, record_inventory_reorder_approval
from tests.utils import default_headers

app = create_app()

client = TestClient(app, headers=default_headers())


def test_metrics_exposes_incident_counters():
    # Trigger an alert
    r = client.post("/api/v1/incident/alert", params={"topic": "security", "message": "test"})
    assert r.status_code == 200
    # Get metrics
    m = client.get("/metrics")
    assert m.status_code == 200
    body = m.text
    assert "shopsquire_incident_alerts_total" in body


def test_metrics_exposes_pricing_latency():
    # Call pricing
    r = client.get("/api/v1/pricing/suggest", params={"uid": "u1", "cart_total_cents": 12000})
    assert r.status_code == 200
    m = client.get("/metrics")
    assert m.status_code == 200
    body = m.text
    assert "shopsquire_pricing_latency_seconds" in body


def test_metrics_exposes_parallel_cache_and_inventory_approval():
    record_parallel_cache_event("hit")
    record_inventory_reorder_approval("required")
    m = client.get("/metrics")
    assert m.status_code == 200
    body = m.text
    assert "shopsquire_parallel_cache_events_total" in body
    assert "shopsquire_inventory_reorder_approvals_total" in body
