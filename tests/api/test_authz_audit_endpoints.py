from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_authz_audit_router_is_registered_and_degrades_gracefully():
    client = TestClient(create_app())

    # Read endpoints respond (empty list if the control-plane tables aren't present
    # yet) rather than 404/500 — proves the router is wired and is defensive.
    r = client.get("/api/v1/authz/decisions", headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200, r.text
    assert "decisions" in r.json()

    r2 = client.get("/api/v1/authz/exceptions?status=open", headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200, r2.text
    assert "exceptions" in r2.json()


def test_authz_policy_endpoint_exposes_live_policy():
    client = TestClient(create_app())
    r = client.get("/api/v1/authz/policy", headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("version")
    assert "refund" in (body.get("actions") or {})


def test_authz_resolve_trigger_runs():
    client = TestClient(create_app())
    r = client.post("/api/v1/authz/exceptions/resolve", headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200, r.text
    assert "summary" in r.json()
