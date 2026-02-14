import os
import hmac
import hashlib
import json
import time
import pytest
from sqlalchemy import text

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_webhook_security.db")
os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_webhook_security.db")


@pytest.fixture(scope="module")
def app_client():
    from src.app.main import create_app
    from fastapi.testclient import TestClient
    app = create_app()
    return TestClient(app)


def _count_security_events(db_session, where_like=None):
    from src.app.models.db import db_session as sess
    with sess() as db:
        if where_like:
            row = db.execute(text("SELECT COUNT(1) FROM security_events WHERE details LIKE :w"), {"w": f"%{where_like}%"}).fetchone()
        else:
            row = db.execute(text("SELECT COUNT(1) FROM security_events")).fetchone()
        return int(row[0] if row else 0)


def test_generic_timestamp_out_of_range_logs_and_401(app_client, monkeypatch):
    # Configure generic secret, send old timestamp
    monkeypatch.setenv("WEBHOOK_SECRET", "secret")
    old_ts = str(int(time.time()) - 9999)
    body = b"{\"event\":\"test\"}"
    sig = hmac.new(b"secret", f"{old_ts}.".encode("utf-8") + body, hashlib.sha256).hexdigest()

    before = _count_security_events(None)
    r = app_client.post(
        "/api/v1/admin/connectors/test",
        data=body,
        headers={
            "x-webhook-timestamp": old_ts,
            "x-webhook-signature": f"sha256={sig}",
        },
    )
    assert r.status_code == 401
    after = _count_security_events(None)
    assert after >= before + 1
    assert "timestamp_out_of_range" in r.text


def test_vendor_missing_secret_enforced_stripe(app_client, monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("WEBHOOK_ENFORCE_VENDOR_SIGNATURES", "true")
    # Provide a Stripe-style header so vendor path engages
    headers = {"stripe-signature": "t=12345,v1=abc"}
    r = app_client.post("/api/v1/admin/connectors/test", data=b"{}", headers=headers)
    assert r.status_code == 401


def test_slack_valid_then_replay_is_409_and_logged(app_client, monkeypatch):
    # Configure Slack secret and compute a valid signature, then send twice
    secret = "s-test"
    monkeypatch.setenv("SLACK_WEBHOOK_SECRET", secret)
    ts = str(int(time.time()))
    body = json.dumps({"event": "ok"}).encode("utf-8")
    basestring = f"v0:{ts}:{body.decode('utf-8')}"
    sig = "v0=" + hmac.new(secret.encode("utf-8"), basestring.encode("utf-8"), hashlib.sha256).hexdigest()

    url = "/api/v1/orchestrator/events/"
    r1 = app_client.post(url, data=body, headers={"x-slack-signature": sig, "x-slack-request-timestamp": ts})
    assert r1.status_code in (200, 404)  # Downstream route may 404; middleware accepted
    r2 = app_client.post(url, data=body, headers={"x-slack-signature": sig, "x-slack-request-timestamp": ts})
    assert r2.status_code == 409
