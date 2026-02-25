from __future__ import annotations

import os
from fastapi.testclient import TestClient

from src.app.main import create_app


def test_login_issues_access_and_refresh_tokens(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", "unit-test-jwt-secret")
    client = TestClient(create_app())

    email = "jwt.user@example.com"
    password = "Secret123!"
    r_reg = client.post("/api/v1/auth/register", json={"email": email, "name": "JWT", "password": password})
    assert r_reg.status_code == 200, r_reg.text
    body = r_reg.json() or {}
    assert isinstance(body.get("access_token"), str) and body.get("access_token")
    assert isinstance(body.get("refresh_token"), str) and body.get("refresh_token")
    assert int(body.get("access_expires_in") or 0) > 0
    assert int(body.get("refresh_expires_in") or 0) > 0


def test_refresh_token_rotates_and_revokes_previous(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", "unit-test-jwt-secret-2")
    client = TestClient(create_app())

    email = "jwt.rotate@example.com"
    password = "Secret123!"
    r_reg = client.post("/api/v1/auth/register", json={"email": email, "name": "JWT", "password": password})
    assert r_reg.status_code == 200, r_reg.text
    rt1 = (r_reg.json() or {}).get("refresh_token")
    assert isinstance(rt1, str) and rt1

    r_refresh = client.post("/api/v1/auth/token/refresh", json={"refresh_token": rt1})
    assert r_refresh.status_code == 200, r_refresh.text
    b2 = r_refresh.json() or {}
    assert isinstance(b2.get("refresh_token"), str) and b2.get("refresh_token")
    assert b2.get("refresh_token") != rt1
    assert isinstance(b2.get("access_token"), str) and b2.get("access_token")

    # Old refresh token should no longer be valid after rotation.
    r_reuse = client.post("/api/v1/auth/token/refresh", json={"refresh_token": rt1})
    assert r_reuse.status_code == 401

