import os
import json

from fastapi.testclient import TestClient


def test_gmail_ingest_rejects_without_secret():
    os.environ.setdefault("GMAIL_INGEST_SECRET", "s1")
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DISABLE_TRACING", "1")
    from src.app.main import create_app

    client = TestClient(create_app())
    r = client.post("/api/v1/ingest/gmail/pubsub", json={})
    assert r.status_code in (401, 503)


def test_gmail_ingest_accepts_canonical_email():
    os.environ["GMAIL_INGEST_SECRET"] = "s1"
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DISABLE_TRACING", "1")
    os.environ.setdefault("RATE_LIMIT_PER_IP_PER_MIN", "0")
    from src.app.main import create_app

    client = TestClient(create_app())
    r = client.post(
        "/api/v1/ingest/gmail/pubsub",
        headers={"X-Ingest-Secret": "s1"},
        json={
            "tenant_id": "t1",
            "email": {
                "message_id": "<m1>",
                "from_addr": "CEO <ceo@microsoft.com>",
                "reply_to": "finance@micros0ft.com",
                "subject": "Urgent wire transfer",
                "body": "Please pay invoice at https://micros0ft-payments.com immediately.",
                "attachments": [{"name": "invoice.html"}],
                "dmarc_fail": False,
            },
        },
    )
    assert r.status_code == 200


def test_m365_validation_token_handshake():
    os.environ.setdefault("M365_INGEST_SECRET", "s2")
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DISABLE_TRACING", "1")
    from src.app.main import create_app

    client = TestClient(create_app())
    r = client.post("/api/v1/ingest/m365/notifications?validationToken=abc123", json={})
    assert r.status_code == 200
    assert r.text == "abc123"


def test_m365_ingest_accepts_canonical_email_with_secret():
    os.environ["M365_INGEST_SECRET"] = "s2"
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DISABLE_TRACING", "1")
    os.environ.setdefault("RATE_LIMIT_PER_IP_PER_MIN", "0")
    from src.app.main import create_app

    client = TestClient(create_app())
    r = client.post(
        "/api/v1/ingest/m365/notifications",
        headers={"X-Ingest-Secret": "s2"},
        json={
            "tenant_id": "t1",
            "email": {
                "message_id": "<m2>",
                "from_addr": "Vendor <billing@supplier.com>",
                "reply_to": "accounts@supplier.com",
                "subject": "Invoice overdue",
                "body": "Pay at http://bad.example.com",
                "attachments": [{"name": "invoice.zip"}],
                "dmarc_fail": False,
            },
        },
    )
    assert r.status_code == 200


def test_gmail_strict_identity_uses_subscription_tenant(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EMAIL_CONNECTOR_IDENTITY_MODE", "strict")
    monkeypatch.setenv(
        "EMAIL_CONNECTOR_SUBSCRIPTIONS_JSON",
        json.dumps(
            {
                "gmail": {
                    "projects/p/subscriptions/sub-a": {
                        "tenant_id": "tenant-authoritative",
                        "audience": "https://shopsquire.example/ingest",
                    }
                }
            }
        ),
    )
    import src.app.routers.ingest_gmail as router

    monkeypatch.setattr(router, "verify_gmail_push_jwt", lambda *args, **kwargs: {"sub": "push"})
    seen = {}

    def fake_persist(identity, email):
        seen["tenant_id"] = identity.tenant_id
        return {"status": "evaluated"}

    monkeypatch.setattr(router, "_persist_or_evaluate", fake_persist)
    from src.app.main import create_app

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/ingest/gmail/pubsub",
        headers={"Authorization": "Bearer signed"},
        json={
            "subscription": "projects/p/subscriptions/sub-a",
            "email": {
                "message_id": "gmail-1",
                "from_addr": "quotes@supplier.example",
                "attachments": [],
            },
        },
    )
    assert response.status_code == 200
    assert seen["tenant_id"] == "tenant-authoritative"

    mismatch = client.post(
        "/api/v1/ingest/gmail/pubsub",
        headers={"Authorization": "Bearer signed", "X-Tenant-Id": "attacker-tenant"},
        json={
            "subscription": "projects/p/subscriptions/sub-a",
            "email": {
                "message_id": "gmail-2",
                "from_addr": "quotes@supplier.example",
                "attachments": [],
            },
        },
    )
    assert mismatch.status_code == 403


def test_m365_strict_identity_rejects_tenant_override(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EMAIL_CONNECTOR_IDENTITY_MODE", "strict")
    monkeypatch.setenv(
        "EMAIL_CONNECTOR_SUBSCRIPTIONS_JSON",
        json.dumps(
            {
                "m365": {
                    "sub-a": {
                        "tenant_id": "tenant-authoritative",
                        "client_state": "state-a",
                    }
                }
            }
        ),
    )
    from src.app.main import create_app

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/ingest/m365/notifications",
        headers={"X-Tenant-Id": "attacker-tenant"},
        json={
            "value": [{"subscriptionId": "sub-a", "clientState": "state-a"}],
        },
    )
    assert response.status_code == 403
