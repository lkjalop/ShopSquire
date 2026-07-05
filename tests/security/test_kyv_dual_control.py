"""Dual-control on the KYV writes that GRANT or REPOINT the RFQ destination. A single compromised
admin credential must not be able to repoint where autonomous RFQs are sent. Enforced only outside
local/dev/test; suspend/revoke stay single-actor (incident response must be fast).

Uses the two REAL distinct dev role keys (owner + developer) so the primary auth AND the second-
approver resolution both go through real get_role_from_key — no monkeypatching of auth."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app

OWNER = "local-owner-key"
DEVELOPER = "local-developer-key"


@pytest.fixture()
def prod_client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")  # not-dev (dual-control enforces) but not prod (no strict-secrets/MFA)
    monkeypatch.setenv("SUPPLY_CHAIN_DUAL_CONTROL", "1")
    return TestClient(create_app(), headers={"x-api-key": OWNER})


def _reg_body(domain="dc-acme.example"):
    return {"legal_name": "Acme Pty Ltd", "verified_domain": domain,
            "contact_email": f"sales@{domain}", "risk_tier": "low"}


def test_register_requires_second_approver(prod_client):
    r = prod_client.post("/api/v1/admin/kyv/vendors", json=_reg_body())
    assert r.status_code == 403 and "dual_control_required" in r.text


def test_self_approval_rejected(prod_client):
    r = prod_client.post("/api/v1/admin/kyv/vendors", json=_reg_body(),
                         headers={"x-approver-token": OWNER})  # same as requestor
    assert r.status_code == 403 and "must differ" in r.text


def test_distinct_owner_approver_passes(prod_client):
    r = prod_client.post("/api/v1/admin/kyv/vendors", json=_reg_body("dc-ok.example"),
                         headers={"x-approver-token": DEVELOPER})  # distinct, owner/dev role
    assert r.status_code == 200, r.text


def test_set_contact_email_requires_dual_control(prod_client):
    r = prod_client.post("/api/v1/admin/kyv/vendors/contact-email",
                         json={"domain": "dc-acme.example", "contact_email": "attacker@evil.example"})
    assert r.status_code == 403 and "dual_control" in r.text


def test_set_contact_email_passes_with_approver(prod_client):
    r = prod_client.post("/api/v1/admin/kyv/vendors/contact-email",
                         json={"domain": "dc-acme.example", "contact_email": "sales@dc-acme.example"},
                         headers={"x-approver-token": DEVELOPER})
    assert r.status_code == 200, r.text


def test_suspend_stays_single_actor(prod_client):
    # reducing trust must NOT require a second approver (fast incident response)
    r = prod_client.post("/api/v1/admin/kyv/vendors/some-id/status", json={"status": "suspended"})
    assert r.status_code != 403


def test_status_verified_requires_dual_control(prod_client):
    r = prod_client.post("/api/v1/admin/kyv/vendors/some-id/status", json={"status": "verified"})
    assert r.status_code == 403 and "dual_control" in r.text


def test_dev_env_is_noop(monkeypatch):
    # default local env: no approver needed (behavior preserved for the demo/dev flow)
    monkeypatch.setenv("APP_ENV", "local")
    c = TestClient(create_app(), headers={"x-api-key": OWNER})
    r = c.post("/api/v1/admin/kyv/vendors", json=_reg_body("dc-dev.example"))
    assert r.status_code == 200, r.text
