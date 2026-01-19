from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def test_support_intents_basic():
    r = client.post("/api/v1/support/intents", params={"text": "I want a refund please"})
    assert r.status_code == 200
    assert r.json()["intent"] == "refund_request"
