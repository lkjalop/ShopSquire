import os
import json
import pytest

os.environ.setdefault("WEBHOOK_SECRET", "secret")
os.environ.setdefault("WEBHOOK_SIGNATURE_HEADER", "x-webhook-signature")
os.environ.setdefault("WEBHOOK_TIMESTAMP_HEADER", "x-webhook-timestamp")
os.environ.setdefault("MERCHANT_API_KEY", "local-merchant-key")


@pytest.fixture(scope="module")
def app_client():
    from src.app.main import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    return TestClient(app)


def _sig(ts: int, body: bytes):
    import hmac, hashlib
    signed = f"{ts}.".encode("utf-8") + body
    return "sha256=" + hmac.new(os.getenv("WEBHOOK_SECRET").encode("utf-8"), signed, hashlib.sha256).hexdigest()


def test_schema_drift_missing_fields_returns_422(app_client):
    ts = 1_700_000_000
    body = json.dumps({"bad": "payload"}).encode("utf-8")
    headers = {
        "x-api-key": os.getenv("MERCHANT_API_KEY"),
        os.getenv("WEBHOOK_SIGNATURE_HEADER"): _sig(ts, body),
        os.getenv("WEBHOOK_TIMESTAMP_HEADER"): str(ts),
        "content-type": "application/json",
    }
    r = app_client.post("/api/v1/orchestrator/events/order_placed", data=body, headers=headers)
    # Pydantic validation should fail with 422; middleware should not cause 500
    assert r.status_code == 422


def test_endpoint_drift_returns_404(app_client):
    ts = 1_700_000_100
    body = json.dumps({"type": "order_placed", "data": {}}).encode("utf-8")
    headers = {
        "x-api-key": os.getenv("MERCHANT_API_KEY"),
        os.getenv("WEBHOOK_SIGNATURE_HEADER"): _sig(ts, body),
        os.getenv("WEBHOOK_TIMESTAMP_HEADER"): str(ts),
        "content-type": "application/json",
    }
    r = app_client.post("/api/v1/orchestrator/events/unknown_path", data=body, headers=headers)
    assert r.status_code == 404
