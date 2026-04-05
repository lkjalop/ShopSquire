from fastapi.testclient import TestClient
from src.app.main import create_app
from tests.utils import default_headers
import os

# Avoid real dependency probes (Redis / Ollama) in unit test context.
os.environ.setdefault("TEST_FAST_HEALTH", "1")

app = create_app()


client = TestClient(app, headers=default_headers())


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_pricing_endpoint_contract():
    r = client.get("/api/v1/pricing/suggest", params={"uid": "u1", "cart_total_cents": 12000})
    assert r.status_code == 200
    body = r.json()
    assert "proposal" in body and "firewall" in body