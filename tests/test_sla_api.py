from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def test_sla_summary_returns_keys():
    # generate some metrics
    client.post("/api/v1/incident/alert", params={"topic": "security", "message": "m"})
    client.get("/api/v1/pricing/suggest", params={"uid": "u1", "cart_total_cents": 12000})
    r = client.get("/api/v1/sla/summary")
    assert r.status_code == 200
    data = r.json()
    assert "incidents_total" in data
    assert "tickets_total" in data
    assert "chaos_total" in data
    assert "pricing_latency_avg_sec" in data
