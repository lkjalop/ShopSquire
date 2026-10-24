"""The local email lab must not mint or disclose an owner credential."""
import secrets

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.app.routers.merchant_dashboard import router


@pytest.mark.parametrize("peer,environment,role,expected", [
    ("127.0.0.1", "test", "owner", 200),
    ("127.0.0.1", "test", "anonymous", 401),
    ("127.0.0.1", "test", "merchant", 403),
    ("198.51.100.10", "test", "owner", 403),
    # Production requires stronger operator authentication before the route.
    # This is an authentication rejection, not proof of the local-only guard.
    ("127.0.0.1", "production", "owner", 401),
])
def test_lab_authority_comes_from_role_environment_and_actual_peer(
        monkeypatch, peer, environment, role, expected):
    owner_key, merchant_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    monkeypatch.setenv("OWNER_API_KEY", owner_key)
    monkeypatch.setenv("MERCHANT_API_KEY", merchant_key)
    monkeypatch.setenv("APP_ENV", environment)
    app = FastAPI()
    app.include_router(router)
    headers = {"host": "localhost", "x-forwarded-for": "127.0.0.1"}
    if role != "anonymous":
        headers["x-api-key"] = owner_key if role == "owner" else merchant_key
    with TestClient(app, client=(peer, 50000)) as client:
        response = client.get("/merchant/email-lab", headers=headers)
    assert response.status_code == expected, response.text[:160]
    assert owner_key not in response.text
    assert owner_key not in str(response.headers)
    if expected == 200:
        assert "ss_csrf=" in response.headers.get("set-cookie", "")
        assert "submitEscalate()" in response.text


def test_production_lab_guard_rejects_an_already_authorized_local_call(monkeypatch):
    from src.app.routers.merchant_dashboard import merchant_email_lab

    monkeypatch.setenv("APP_ENV", "production")
    request = Request({"type": "http", "method": "GET", "path": "/merchant/email-lab",
                       "scheme": "http", "query_string": b"", "headers": [],
                       "client": ("127.0.0.1", 50000), "server": ("localhost", 80)})
    # The route's environment guard is independent of its role dependency.
    with pytest.raises(HTTPException) as rejected:
        merchant_email_lab(request)
    assert rejected.value.status_code == 403
