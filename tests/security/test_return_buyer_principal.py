import time

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
from src.app.security.buyer_principal import resolve_buyer_principal


def _request(token: str) -> Request:
    return Request({
        "type": "http", "method": "POST", "path": "/api/v1/returns/claims",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
    })


def _token(secret: str, subject: str) -> str:
    now = int(time.time())
    return jwt.encode({
        "sub": subject, "typ": "access", "iat": now, "exp": now + 300,
        "iss": "shopsquire", "aud": "shopsquire-api",
    }, secret, algorithm="HS256")


def test_verified_claimant_overrides_no_client_identity(monkeypatch):
    secret = "return-test-secret"
    monkeypatch.setenv("JWT_SIGNING_KEY", secret)
    monkeypatch.setenv("BUYER_TENANT_BINDINGS_JSON", '{"buyer-a":["tenant-a"]}')
    token = set_active_tenant_id("tenant-a")
    try:
        principal = resolve_buyer_principal(_request(_token(secret, "buyer-a")))
        assert principal.subject == "buyer-a"
        assert principal.tenant_id == "tenant-a"
        assert principal.verified is True
    finally:
        reset_active_tenant_id(token)

def test_body_uid_cannot_select_another_claimant(monkeypatch):
    secret = "return-test-secret"
    monkeypatch.setenv("JWT_SIGNING_KEY", secret)
    monkeypatch.setenv("BUYER_TENANT_BINDINGS_JSON", '{"buyer-a":["tenant-a"]}')
    token = set_active_tenant_id("tenant-a")
    try:
        with pytest.raises(HTTPException) as exc:
            resolve_buyer_principal(
                _request(_token(secret, "buyer-a")), supplied_uid="buyer-b"
            )
        assert exc.value.status_code == 403
        assert exc.value.detail == "buyer_identity_mismatch"
    finally:
        reset_active_tenant_id(token)
