"""Stripe webhook fail-closed contract.

In non-dev environments an unsigned/unverifiable webhook (no STRIPE_WEBHOOK_SECRET)
MUST be rejected before any order-state mutation — a forged event can never
transition an order to paid/refunded. In dev/test the unsigned path is allowed
(processes raw JSON) so the flow can be exercised without Stripe configured.

This exercises the route handler against a minimal middleware-free app: the fix
lives entirely in the handler branch, and the full app's cold-start middleware
makes a blocking outbound call on the first isolated request (it only returns
fast once the suite has warmed the service-down caches). The non-dev branch is
isolated by patching payments._is_non_dev_env so the test never depends on the
cached Settings.app_env.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.routers import payments


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(payments.router)
    return TestClient(app)


def test_webhook_fail_closed_in_non_dev_without_secret(monkeypatch):
    # Force "non-dev" and ensure no webhook secret is configured. The handler must
    # reject BEFORE touching the DB, so no db stub is needed here.
    monkeypatch.setattr(payments, "_is_non_dev_env", lambda _env: True)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    client = _client()
    payload = {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_forged"}}}
    r = client.post("/api/v1/payments/webhook", data=json.dumps(payload))
    assert r.status_code == 503, r.text
    assert "STRIPE_WEBHOOK_SECRET" in r.text


def test_webhook_dev_without_secret_still_processes(monkeypatch):
    # Dev/test env (the default) keeps the unsigned fallback so local flows work.
    monkeypatch.setattr(payments, "_is_non_dev_env", lambda _env: False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    # The dev path performs an orders UPDATE; stub db_session so the test asserts the
    # routing/branch (accepted + processed, not 503) without depending on schema.
    @contextmanager
    def _fake_session():
        class _R:
            rowcount = 0
        class _DB:
            def execute(self, *a, **k):
                return _R()
            def commit(self):
                pass
        yield _DB()

    monkeypatch.setattr(payments, "db_session", _fake_session)

    client = _client()
    payload = {"type": "payment_intent.succeeded", "data": {"object": {"id": "pi_dev"}}}
    r = client.post("/api/v1/payments/webhook", data=json.dumps(payload))
    assert r.status_code == 200, r.text


def test_webhook_dedups_repeat_event_delivery(monkeypatch, tmp_path):
    # M4: Stripe retries delivery — the same event.id must be processed ONCE (no double ledger /
    # inventory / settlement). Dev path (no secret) processes raw JSON; assert the 2nd is a duplicate.
    import src.app.models.db as db_module
    from sqlalchemy import create_engine
    monkeypatch.setattr(payments, "_is_non_dev_env", lambda _env: False)
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'evt.sqlite'}", future=True)
    original = db_module.engine
    db_module.set_engine(engine)
    try:
        client = _client()
        evt = {"id": "evt_dedup_1", "type": "payment_intent.payment_failed",
               "data": {"object": {"id": "pi_none"}}}
        r1 = client.post("/api/v1/payments/webhook", data=json.dumps(evt))
        r2 = client.post("/api/v1/payments/webhook", data=json.dumps(evt))
        assert r1.status_code == 200 and not r1.json().get("duplicate")
        assert r2.status_code == 200 and r2.json().get("duplicate") is True
    finally:
        db_module.set_engine(original)
