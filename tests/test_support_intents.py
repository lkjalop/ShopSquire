from fastapi.testclient import TestClient
from src.app.main import create_app
from tests.utils import default_headers

app = create_app()
client = TestClient(app, headers=default_headers())


def test_support_intents_basic():
    r = client.post("/api/v1/support/intents", params={"text": "I want a refund please"})
    assert r.status_code == 200
    assert r.json()["intent"] == "refund_request"