"""KYV vendor onboarding/lifecycle — the owner control plane that feeds the autonomous-send trust gate.
Register → verify → resolve by domain; an invalid registration number is rejected; verifying a vendor is
exactly what makes its domain acceptable to the WS-C trust check."""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app


def _client():
    return TestClient(create_app(), headers={"x-api-key": "local-owner-key"})


def test_register_then_verify_then_resolve_and_trust():
    c = _client()
    domain = "wsd-acme-supplies.example"
    r = c.post("/api/v1/admin/kyv/vendors",
               json={"legal_name": "Acme Supplies Pty Ltd", "verified_domain": domain,
                     "contact_email": f"sales@{domain}", "risk_tier": "low"})
    assert r.status_code == 200, r.text
    vid = r.json()["vendor_id"]
    assert r.json()["status"] in ("pending", "verified")

    v = c.post(f"/api/v1/admin/kyv/vendors/{vid}/verify")
    assert v.status_code == 200 and v.json()["status"] == "verified"

    got = c.get(f"/api/v1/admin/kyv/vendors/by-domain/{domain}")
    assert got.status_code == 200 and got.json()["status"] == "verified" and got.json()["risk_tier"] == "low"

    # the autonomous-send trust gate now accepts this domain (verified + risk ≤ medium)
    from src.app.services.fulfillment.autonomous_send import _kyv_trusted
    assert _kyv_trusted(domain, "default", None) is True


def test_invalid_registration_number_is_rejected():
    c = _client()
    r = c.post("/api/v1/admin/kyv/vendors",
               json={"legal_name": "Bad Reg Co", "registration_number": "123", "registration_type": "abn"})
    assert r.status_code == 400


def test_suspend_revokes_autonomous_trust():
    c = _client()
    domain = "wsd-suspendme.example"
    vid = c.post("/api/v1/admin/kyv/vendors",
                 json={"legal_name": "Suspend Me Ltd", "verified_domain": domain, "risk_tier": "low"}).json()["vendor_id"]
    c.post(f"/api/v1/admin/kyv/vendors/{vid}/verify")
    from src.app.services.fulfillment.autonomous_send import _kyv_trusted
    assert _kyv_trusted(domain, "default", None) is True
    s = c.post(f"/api/v1/admin/kyv/vendors/{vid}/status", json={"status": "suspended"})
    assert s.status_code == 200
    assert _kyv_trusted(domain, "default", None) is False  # suspension instantly removes trust
