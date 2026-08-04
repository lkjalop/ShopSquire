"""P2 PCI DSS 4.0.1 quartet:
  1. AdminMfaMiddleware defaults ON in production (Req 8.3/8.4), stays opt-in for dev.
  2. PAN detected in a payment request opens an INCIDENT, not just telemetry (Req 12.10.7).
  3. Carrier webhooks fail CLOSED (503) in non-dev when the HMAC secret is unset (order-state
     forgery vector) but keep warn-and-accept in dev.
  4. Payment endpoints assert TLS in production (Req 4.2.1) — 403 tls_required over plain http.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_admin_mfa_defaults_on_in_production(monkeypatch):
    from src.app.security.admin_mfa import AdminMfaMiddleware
    monkeypatch.delenv("ADMIN_MFA_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert AdminMfaMiddleware(lambda *_: None).enabled is True
    monkeypatch.setenv("APP_ENV", "local")
    assert AdminMfaMiddleware(lambda *_: None).enabled is False
    # explicit override still wins in prod
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_MFA_ENABLED", "0")
    assert AdminMfaMiddleware(lambda *_: None).enabled is False


def _compliance_app() -> FastAPI:
    from src.app.security.compliance import ComplianceMiddleware
    app = FastAPI()
    app.add_middleware(ComplianceMiddleware)

    @app.post("/api/v1/payments/echo")
    def echo(body: dict):
        return {"ok": True}

    return app


def test_pan_detection_opens_incident(monkeypatch):
    calls = []
    import src.app.observability.metrics as metrics
    monkeypatch.setattr(metrics, "record_incident_alert", lambda topic, sev: calls.append((topic, sev)))
    c = TestClient(_compliance_app())
    r = c.post("/api/v1/payments/echo",
               json={"note": "card 4111 1111 1111 1111 cvv 123 exp 12/27"})
    assert r.status_code == 422
    assert ("pci_pan_in_request", "p1") in calls


def test_payment_tls_asserted_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("REQUIRE_TLS_FOR_PAYMENTS", raising=False)
    c = TestClient(_compliance_app())  # TestClient scheme is http, no x-forwarded-proto
    r = c.post("/api/v1/payments/echo", json={"a": 1})
    assert r.status_code == 403 and r.json().get("detail") == "tls_required"
    # forwarded-as-https passes the gate
    r2 = c.post("/api/v1/payments/echo", json={"a": 1}, headers={"x-forwarded-proto": "https"})
    assert r2.status_code == 200
    # dev is untouched
    monkeypatch.setenv("APP_ENV", "local")
    assert TestClient(_compliance_app()).post("/api/v1/payments/echo", json={"a": 1}).status_code == 200


def test_carrier_webhook_fails_closed_outside_dev(monkeypatch):
    from src.app.routers import shipping_webhooks
    app = FastAPI()
    app.include_router(shipping_webhooks.router)
    c = TestClient(app)
    payload = {"description": "tracker.updated", "result": {"tracking_code": "T1", "status": "in_transit"}}
    monkeypatch.delenv("EASYPOST_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    r = c.post("/api/v1/shipping/webhook/easypost", content=json.dumps(payload),
               headers={"Content-Type": "application/json"})
    assert r.status_code == 503
    monkeypatch.setenv("APP_ENV", "local")
    r2 = c.post("/api/v1/shipping/webhook/easypost", content=json.dumps(payload),
                headers={"Content-Type": "application/json"})
    assert r2.status_code == 200  # dev warn-and-accept preserved
