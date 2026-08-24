"""PCI #5 — real per-admin TOTP MFA end-to-end (enroll -> confirm -> gated access).

With ADMIN_MFA_ENABLED, an admin must enroll a TOTP secret and confirm it, after which /api/v1/admin
requires a valid time-based code (not a single shared static OTP). The enrollment routes themselves
are exempt so a fresh admin can bootstrap.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from src.app import main as main_module
from src.app.security import totp
from src.app.security.auth import ROLE_OWNER


def _owner_key():
    return os.getenv("OWNER_API_KEY", "local-owner-key")


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_MFA_ENABLED", "1")
    monkeypatch.delenv("ADMIN_MFA_OTP", raising=False)
    # Ensure a clean slate for the owner principal (create the table first if it doesn't exist yet).
    from sqlalchemy import text
    from src.app.models.db import db_session
    from src.app.security.mfa_store import _ensure_table
    with db_session() as db:
        _ensure_table(db)
        db.execute(text("DELETE FROM admin_mfa_secrets WHERE principal = :p"), {"p": ROLE_OWNER})
        db.commit()
    # MFA is startup-time middleware configuration.  The suite-wide
    # memory-safe app factory deliberately returns a per-DATABASE_URL
    # singleton, so using it here would leave MFA enabled on the shared app
    # after monkeypatch restores the environment.  Build the one deliberately
    # configured app directly and keep the shared singleton unchanged.
    return TestClient(main_module._original_create_app())


def test_enroll_returns_secret_and_otpauth_uri(client):
    r = client.post("/api/v1/admin/mfa/enroll", headers={"x-api-key": _owner_key()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["secret"] and body["otpauth_uri"].startswith("otpauth://totp/")
    assert body["principal"] == ROLE_OWNER


def test_enroll_requires_admin_key(client):
    r = client.post("/api/v1/admin/mfa/enroll", headers={"x-api-key": "not-a-key"})
    assert r.status_code == 401


def test_confirm_with_valid_code_then_status_confirmed(client):
    enroll = client.post("/api/v1/admin/mfa/enroll", headers={"x-api-key": _owner_key()}).json()
    code = totp.now_code(enroll["secret"])
    r = client.post("/api/v1/admin/mfa/confirm", headers={"x-api-key": _owner_key()}, json={"code": code})
    assert r.status_code == 200, r.text
    assert r.json()["confirmed"] is True
    status = client.get("/api/v1/admin/mfa/status", headers={"x-api-key": _owner_key()}).json()
    assert status["enrolled"] is True and status["confirmed"] is True


def test_confirm_with_bad_code_rejected(client):
    enroll = client.post("/api/v1/admin/mfa/enroll", headers={"x-api-key": _owner_key()}).json()
    bad = "000000" if totp.now_code(enroll["secret"]) != "000000" else "111111"
    r = client.post("/api/v1/admin/mfa/confirm", headers={"x-api-key": _owner_key()}, json={"code": bad})
    assert r.status_code == 401


def test_store_roundtrip():
    from src.app.security.mfa_store import set_secret, get_secret, confirm, is_enrolled
    set_secret("developer", "JBSWY3DPEHPK3PXP")
    secret, confirmed = get_secret("developer")
    assert secret == "JBSWY3DPEHPK3PXP" and confirmed is False
    assert is_enrolled("developer") is False
    assert confirm("developer") is True
    assert is_enrolled("developer") is True
