"""Only authenticated bearers may supply a person identity alongside an API key."""

import time
import uuid

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.app.security import auth

KEY = "synthetic-signing-key-for-identity-tests-only-32-bytes"


@pytest.fixture(autouse=True)
def isolated_identity_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SIGNING_KEY", KEY)
    monkeypatch.setenv("JWT_ISSUER", "shopsquire")
    monkeypatch.setenv("JWT_AUDIENCE", "shopsquire-api")
    for name in ("OIDC_JWKS_URL", "OIDC_INTROSPECTION_URL"):
        monkeypatch.delenv(name, raising=False)


def bearer(**changes):
    claims = {
        "sub": "owned-synthetic-person",
        "email": "person@example.test",
        "role": "owner",
        "iss": "shopsquire",
        "aud": "shopsquire-api",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
    }
    claims.update(changes)
    return "Bearer " + jwt.encode(claims, KEY, algorithm="HS256")


@pytest.mark.parametrize(
    "changes",
    [
        {"exp": 1},
        {"iss": "other-issuer"},
        {"aud": "other-audience"},
        {"iat": int(time.time()) + 600},
    ],
)
def test_invalid_bearer_cannot_supply_person_or_email(changes):
    token = bearer(**changes)
    assert auth._bearer_subject(token) is None
    assert auth._bearer_email(token) is None


def test_valid_signed_bearer_supplies_verified_person():
    token = bearer()
    subject = auth.operator_subject(authorization=token)
    assert subject.user_id == "owned-synthetic-person"
    assert subject.email == "person@example.test"


def test_valid_api_key_does_not_authenticate_an_unrelated_forged_person(monkeypatch):
    key = "synthetic-owner-" + uuid.uuid4().hex
    monkeypatch.setenv("OWNER_API_KEY", key)
    monkeypatch.setenv("ABAC_ENABLED", "0")
    observed = []
    monkeypatch.setattr(
        "src.app.services.operator_tenant_membership.authorize_request_membership",
        lambda **kw: observed.append(kw["bearer_subject"]),
    )
    app = FastAPI()

    @app.get("/probe", dependencies=[Depends(auth.require_role([auth.ROLE_OWNER]))])
    def probe(person=Depends(auth.operator_subject)):
        return {"person": person.user_id, "email": person.email}

    forged = bearer().rsplit(".", 1)[0] + ".forged-signature"
    response = TestClient(app, client=("198.51.100.237", 50000)).get(
        "/probe", headers={"x-api-key": key, "authorization": forged}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"person": "", "email": ""}
    assert observed == [None]


def test_missing_environment_is_not_permission_to_use_default_keys(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    for name in (
        "OWNER_API_KEY",
        "MERCHANT_API_KEY",
        "DEVELOPER_API_KEY",
        "OWNER_API_KEY_REF",
        "MERCHANT_API_KEY_REF",
        "DEVELOPER_API_KEY_REF",
    ):
        monkeypatch.delenv(name, raising=False)
    for value in ("local-owner-key", "local-merchant-key", "local-developer-key"):
        assert auth.get_role_from_key(value) is None


@pytest.mark.parametrize("environment", [None, "", "  "])
def test_unset_environment_enables_production_auth_controls(monkeypatch, environment):
    if environment is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.delenv("ABAC_ENABLED", raising=False)
    monkeypatch.delenv("ADMIN_OIDC_REQUIRED", raising=False)
    assert auth._abac_enabled() is True
    assert auth._admin_oidc_required() is True
