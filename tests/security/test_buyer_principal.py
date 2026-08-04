from __future__ import annotations

import time

import jwt
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.app.security.buyer_principal import resolve_buyer_principal


def _request(*, authorization: str = "") -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def _access_token(secret: str, subject: str = "buyer-1") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": subject,
            "typ": "access",
            "iss": "shopsquire",
            "aud": "shopsquire-api",
            "iat": now,
            "exp": now + 300,
        },
        secret,
        algorithm="HS256",
    )


def test_verified_access_token_is_authoritative(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", "test-secret")
    principal = resolve_buyer_principal(
        _request(authorization=f"Bearer {_access_token('test-secret')}"),
        supplied_uid="buyer-1",
    )
    assert principal and principal.subject == "buyer-1"
    assert principal.verified is True


def test_tampered_token_is_rejected_in_strict_mode(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", "correct-secret")
    monkeypatch.setenv("BUYER_IDENTITY_MODE", "strict")
    with pytest.raises(HTTPException) as exc:
        resolve_buyer_principal(
            _request(authorization=f"Bearer {_access_token('wrong-secret')}"),
            supplied_uid="buyer-1",
        )
    assert exc.value.status_code == 401


def test_body_uid_cannot_switch_verified_subject(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", "test-secret")
    with pytest.raises(HTTPException) as exc:
        resolve_buyer_principal(
            _request(authorization=f"Bearer {_access_token('test-secret')}"),
            supplied_uid="buyer-2",
        )
    assert exc.value.status_code == 403


def test_body_only_identity_is_compatibility_only(monkeypatch):
    monkeypatch.setenv("BUYER_IDENTITY_MODE", "compat")
    principal = resolve_buyer_principal(_request(), supplied_uid="legacy-buyer")
    assert principal and principal.verified is False
    monkeypatch.setenv("BUYER_IDENTITY_MODE", "strict")
    with pytest.raises(HTTPException) as exc:
        resolve_buyer_principal(_request(), supplied_uid="legacy-buyer")
    assert exc.value.status_code == 401
