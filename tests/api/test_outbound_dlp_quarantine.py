"""Outbound-DLP human-release queue: a secret-blocked send parks for owner review; the owner can
inspect, release (re-send with the block bypassed), or discard. Owner-only."""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

OWNER = {"x-api-key": os.getenv("OWNER_API_KEY", "local-owner-key")}
MERCHANT = {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}


@pytest.fixture()
def env(monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    _dbmod.set_engine(eng)
    from src.app.routers.outbound_email_quarantine import router
    app = FastAPI()
    app.include_router(router)
    try:
        yield TestClient(app)
    finally:
        _dbmod.engine = orig
        _dbmod.set_engine(orig)


def _park_a_secret_send():
    # a secret-bearing send parks in quarantine (email_providers block path)
    from src.app.services.email_providers import SendGridProvider
    r = SendGridProvider().send(to="v@vendor.com", subject="creds",
                                body="licence key sk_live_abcdef0123456789ABCDEF", agent_id="Email_Send_Agent")
    assert r["ok"] is False and r["blocked"] and r["error"] == "dlp_content_block"
    assert r["quarantine_id"]
    return r["quarantine_id"]


def test_blocked_send_parks_and_owner_lists_it(env):
    qid = _park_a_secret_send()
    r = env.get("/api/v1/email/outbound/quarantine", headers=OWNER)
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert qid in ids
    # the LIST must not leak the body
    item = next(i for i in r.json()["items"] if i["id"] == qid)
    assert "body" not in item and item["dlp"]["action"] == "block"


def test_list_is_owner_only(env):
    _park_a_secret_send()
    assert env.get("/api/v1/email/outbound/quarantine", headers=MERCHANT).status_code in (401, 403)


def test_inspect_returns_body_for_owner(env):
    qid = _park_a_secret_send()
    r = env.get(f"/api/v1/email/outbound/quarantine/{qid}", headers=OWNER)
    assert r.status_code == 200 and "sk_live_" in r.json()["body"]


def test_release_resends_and_marks_released(env, monkeypatch):
    qid = _park_a_secret_send()
    sent = {}

    class _Prov:
        def send(self, to, subject, body, **kw):
            sent.update({"to": to, "bypass": kw.get("_dlp_release")})
            return {"ok": True, "dev": True}
    import src.app.routers.outbound_email_quarantine as mod
    monkeypatch.setattr(mod, "get_default_email_provider", lambda: _Prov(), raising=False)
    # patch the lazily-imported symbol
    import src.app.services.email_providers as ep
    monkeypatch.setattr(ep, "get_default_email_provider", lambda: _Prov())

    r = env.post(f"/api/v1/email/outbound/quarantine/{qid}/release", headers=OWNER)
    assert r.status_code == 200 and r.json()["status"] == "released"
    assert sent["bypass"] is True, "release must re-send with the DLP block bypassed"
    # second release is a no-op (already released)
    r2 = env.post(f"/api/v1/email/outbound/quarantine/{qid}/release", headers=OWNER)
    assert r2.status_code == 409


def test_discard_never_sends(env):
    qid = _park_a_secret_send()
    r = env.post(f"/api/v1/email/outbound/quarantine/{qid}/discard", headers=OWNER)
    assert r.status_code == 200 and r.json()["status"] == "discarded"
    # gone from the pending queue
    lst = env.get("/api/v1/email/outbound/quarantine", headers=OWNER).json()["items"]
    assert qid not in [i["id"] for i in lst]
