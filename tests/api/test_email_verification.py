"""Native email verification: register issues a signed link (unverified), verify-email marks the
account verified AND bulk-merges matching guest orders to the now-verified member."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", "test-secret-abc")
    monkeypatch.setenv("APP_ENV", "test")  # dev path logs the link, no SMTP
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng; _dbmod.set_engine(eng)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT, guest_email_hash TEXT, "
                       "total_cents INTEGER, status TEXT)"))
    from src.app.routers import auth
    app = FastAPI()
    app.include_router(auth.router)
    try:
        yield TestClient(app), auth
    finally:
        _dbmod.engine = orig; _dbmod.set_engine(orig)


def test_register_is_unverified_then_verify(client):
    c, auth = client
    r = c.post("/api/v1/auth/register", json={"email": "u@x.com", "password": "hunter2secret", "name": "U"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["email_verified"] is False and d["verification_email_sent"] is True
    uid = d["user_id"]

    # seed a GUEST order with this email's hash BEFORE verifying
    from src.app.services.pii_crypto import pii_hash
    from src.app.models.db import db_session
    with db_session() as db:
        db.execute(text("INSERT INTO orders (id, customer_id, guest_email_hash, total_cents, status) "
                        "VALUES ('G-1', NULL, :h, 5000, 'paid')"), {"h": pii_hash("u@x.com")})
        db.commit()

    # forge the verify token via the same issuer and hit the endpoint
    tok = auth._issue_email_verification_token(uid, "u@x.com")
    v = c.get("/api/v1/auth/verify-email", params={"token": tok})
    assert v.status_code == 200, v.text
    vd = v.json()
    assert vd["verified"] is True and vd["guest_orders_merged"] == 1  # the guest order got claimed

    with db_session() as db:
        ver = db.execute(text("SELECT email_verified FROM user_accounts WHERE id=:i"), {"i": uid}).scalar()
        owner = db.execute(text("SELECT customer_id FROM orders WHERE id='G-1'")).scalar()
    assert int(ver or 0) == 1 and owner == uid


def test_bad_token_rejected(client):
    c, _ = client
    assert c.get("/api/v1/auth/verify-email", params={"token": "garbage"}).status_code == 400
