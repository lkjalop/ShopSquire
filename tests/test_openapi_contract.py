from fastapi.testclient import TestClient
from src.app.main import app


client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_pricing_endpoint_contract():
    r = client.get("/api/v1/pricing/suggest", params={"uid": "u1", "cart_total_cents": 12000})
    assert r.status_code == 200
    body = r.json()
    assert "proposal" in body and "firewall" in body
