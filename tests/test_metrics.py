from fastapi.testclient import TestClient
from src.app.main import app
from src.app.config import get_settings
import json

client = TestClient(app)


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
