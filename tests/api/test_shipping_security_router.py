import hashlib
import hmac
import json
import os

from fastapi.testclient import TestClient

from src.app.main import create_app


def _client_with_env(monkeypatch, *, secret: str) -> TestClient:
    monkeypatch.setenv("EGRESS_ALLOWLIST_ENABLED", "0")
    monkeypatch.setenv("SHIPPING_WEBHOOK_SECRET", secret)
    return TestClient(create_app())


def _sig(secret: str, raw: bytes) -> str:
    s = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return f"sha256={s}"


def test_shipping_webhook_signature_and_replay(monkeypatch):
    secret = "ship-secret-test"
    client = _client_with_env(monkeypatch, secret=secret)
    payload = {
        "shipment_id": "SHIP-1",
        "provider": "auspost",
        "status": "picked_up",
        "tenant_id": "t1",
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    headers = {
        "x-api-key": "local-merchant-key",
        "x-shipping-signature": _sig(secret, raw),
        "x-shipping-nonce": "nonce-1",
        "content-type": "application/json",
    }
    r1 = client.post("/api/v1/shipping/webhooks/provider", headers=headers, content=raw)
    assert r1.status_code == 200
    r2 = client.post("/api/v1/shipping/webhooks/provider", headers=headers, content=raw)
    assert r2.status_code == 409


def test_shipping_reroute_requires_stepup_and_owner_scope(monkeypatch):
    client = _client_with_env(monkeypatch, secret="ship-secret-test")
    body = {
        "shipment_id": "SHIP-2",
        "tenant_id": "tenant-a",
        "owner_id": "user-1",
        "new_address": "1 New St",
    }
    h = {"x-api-key": "local-merchant-key", "x-tenant-id": "tenant-a", "x-user-id": "user-1"}
    r1 = client.post("/api/v1/shipping/reroute/request", headers=h, json=body)
    assert r1.status_code == 401
    body["mfa_stepup_token"] = "stepup-ok"
    r2 = client.post("/api/v1/shipping/reroute/request", headers=h, json=body)
    assert r2.status_code == 200
    assert r2.json().get("status") == "pending_provider_confirm"
    h_bad = {"x-api-key": "local-merchant-key", "x-tenant-id": "tenant-a", "x-user-id": "user-2"}
    r3 = client.post("/api/v1/shipping/reroute/request", headers=h_bad, json=body)
    assert r3.status_code == 403
