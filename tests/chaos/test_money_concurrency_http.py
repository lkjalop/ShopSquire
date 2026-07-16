"""Money-P0 M5 — concurrent HTTP integration races (GPT-5.6 roadmap #2).

The SQL-primitive suite (test_money_concurrency_postgres.py) races reserve_refund_slot /
release_inventory / the order CAS in isolation. THIS races the full HANDLER stack over HTTP —
routing + endpoint logic + DB + the webhook dedup. The event-dedup race (unique-key INSERT) is
atomic on SQLite and always runs; the order-transition row-lock race needs real Postgres
(TEST_POSTGRES_URL) — SQLite's non-serializable isolation can't model it, exactly as the primitive
suite documents.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

MERCHANT = {"x-api-key": "local-merchant-key"}


def _fire(n, work):
    barrier = threading.Barrier(n)

    def contender(i):
        barrier.wait(timeout=10)
        return work(i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        return [f.result(timeout=25) for f in [pool.submit(contender, i) for i in range(n)]]


def _client_on(engine):
    import src.app.models.db as db_module
    original = db_module.engine
    db_module.set_engine(engine)
    from src.app.routers import payments, orders
    app = FastAPI()
    app.include_router(orders.router)
    app.include_router(payments.router)
    return TestClient(app, raise_server_exceptions=False), db_module, original


def test_concurrent_webhook_same_event_processed_once(tmp_path):
    """M4 dedup under concurrent delivery through the REAL webhook handler (atomic on SQLite)."""
    import src.app.routers.payments as payments
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'m5.sqlite'}", future=True)
    client, db_module, original = _client_on(engine)
    payments._is_non_dev_env = lambda _e: False
    try:
        with db_module.db_session() as db:
            db.execute(text("INSERT INTO orders (id, status, total_cents, currency, stripe_intent_id) "
                            "VALUES ('ORD-W5','created',5000,'USD','pi_w5')"))
            db.commit()
        evt = {"id": "evt_m5_race", "type": "payment_intent.payment_failed",
               "data": {"object": {"id": "pi_w5"}}}
        def deliver(_i):
            response = client.post("/api/v1/payments/webhook", data=json.dumps(evt))
            return response.status_code, response.json().get("duplicate") is True

        results = _fire(5, deliver)
        assert results.count((200, False)) == 1, f"exactly one delivery processes: {results}"
        assert all(r == (200, False) or r == (200, True) or r[0] == 503 for r in results)
    finally:
        db_module.set_engine(original)


def test_claimed_event_failure_is_retryable(monkeypatch, tmp_path):
    import src.app.routers.payments as payments
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'claim-retry.sqlite'}", future=True)
    client, db_module, original = _client_on(engine)
    payments._is_non_dev_env = lambda _e: False
    real_apply = payments._apply_payment_webhook_event
    calls = {"n": 0}

    def fail_once(event, *, event_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("crash after inbox claim")
        return real_apply(event, event_id=event_id)

    monkeypatch.setattr(payments, "_apply_payment_webhook_event", fail_once)
    event = {"id": "evt_claim_retry", "type": "payment_intent.succeeded",
             "data": {"object": {"id": "pi_missing"}}}
    try:
        first = client.post("/api/v1/payments/webhook", data=json.dumps(event))
        second = client.post("/api/v1/payments/webhook", data=json.dumps(event))
        assert first.status_code == 503
        assert second.status_code == 200 and second.json()["event_id"] == "evt_claim_retry"
        with db_module.db_session() as db:
            assert db.execute(text(
                "SELECT state FROM stripe_events WHERE event_id='evt_claim_retry'")) .scalar() == "processed"
    finally:
        db_module.set_engine(original)


def test_failed_inventory_release_rolls_back_and_retries(monkeypatch, tmp_path):
    import src.app.routers.payments as payments
    import src.app.services.inventory_guard as inventory_guard
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'release-retry.sqlite'}", future=True)
    client, db_module, original = _client_on(engine)
    payments._is_non_dev_env = lambda _e: False
    real_release = inventory_guard.release_inventory_for_order
    calls = {"n": 0}

    def fail_once(db, *, order_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("inventory store unavailable")
        return real_release(db, order_id=order_id)

    monkeypatch.setattr(inventory_guard, "release_inventory_for_order", fail_once)
    try:
        with db_module.db_session() as db:
            db.execute(text("CREATE TABLE IF NOT EXISTS inventory_reservations (id TEXT PRIMARY KEY, order_id TEXT, sku TEXT, qty INT, status TEXT, created_at TEXT, updated_at TEXT)"))
            db.execute(text("DELETE FROM inventory_reservations"))
            db.execute(text("DELETE FROM inventory"))
            db.execute(text("DELETE FROM products"))
            db.execute(text("INSERT INTO products (id,sku,name,price_cents,currency,active) VALUES ('p1','SKU-1','Test',100,'USD',1)"))
            db.execute(text("INSERT INTO inventory (id,product_id,stock,warehouse,updated_at) VALUES ('i1','p1',7,'default',CURRENT_TIMESTAMP)"))
            db.execute(text("INSERT INTO inventory_reservations VALUES ('r1','ORD-R','SKU-1',3,'reserved',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
            db.execute(text("INSERT INTO orders (id,status,total_cents,currency,stripe_intent_id) VALUES ('ORD-R','created',5000,'USD','pi_release')"))
            db.commit()
        event = {"id": "evt_release_retry", "type": "payment_intent.payment_failed",
                 "data": {"object": {"id": "pi_release"}}}
        assert client.post("/api/v1/payments/webhook", data=json.dumps(event)).status_code == 503
        with db_module.db_session() as db:
            assert db.execute(text("SELECT status FROM orders WHERE id='ORD-R'")) .scalar() == "created"
            assert db.execute(text("SELECT stock FROM inventory WHERE id='i1'")) .scalar() == 7
        assert client.post("/api/v1/payments/webhook", data=json.dumps(event)).status_code == 200
        with db_module.db_session() as db:
            assert db.execute(text("SELECT status FROM orders WHERE id='ORD-R'")) .scalar() == "payment_failed"
            assert db.execute(text("SELECT stock FROM inventory WHERE id='i1'")) .scalar() == 10
    finally:
        db_module.set_engine(original)


def test_outbox_failure_survives_provider_state_commit(monkeypatch, tmp_path):
    import src.app.routers.payments as payments
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'outbox-retry.sqlite'}", future=True)
    client, db_module, original = _client_on(engine)
    payments._is_non_dev_env = lambda _e: False
    seen = []
    monkeypatch.setattr(payments, "_handle_payment_outbox_job",
                        lambda *_args: (_ for _ in ()).throw(RuntimeError("worker down")))
    try:
        with db_module.db_session() as db:
            db.execute(text("INSERT INTO orders (id,status,total_cents,currency,stripe_intent_id) VALUES ('ORD-O','created',5000,'USD','pi_outbox')"))
            db.commit()
        event = {"id": "evt_outbox", "type": "payment_intent.succeeded",
                 "data": {"object": {"id": "pi_outbox"}}}
        first = client.post("/api/v1/payments/webhook", data=json.dumps(event))
        assert first.status_code == 200 and first.json()["outbox"]["failed"] == 2
        monkeypatch.setattr(payments, "_handle_payment_outbox_job",
                            lambda kind, payload: seen.append((kind, payload["intent_id"])))
        retry = client.post("/api/v1/payments/webhook", data=json.dumps(event))
        assert retry.status_code == 200 and retry.json()["duplicate"] is True
        assert {kind for kind, _ in seen} == {"ledger_payment_succeeded", "dispatch_paid_order"}
    finally:
        db_module.set_engine(original)


def test_concurrent_order_transitions_one_winner_postgres():
    """The order CAS via HTTP under a TRUE row-lock race (Postgres only; SQLite can't model it)."""
    url = os.getenv("TEST_POSTGRES_URL")
    if not url or not url.startswith(("postgres", "postgresql")):
        pytest.skip("TEST_POSTGRES_URL (Postgres) required for the true order-transition race")
    admin = create_engine(url, future=True)
    schema = f"m5_http_{uuid.uuid4().hex[:10]}"
    with admin.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"}, future=True)
    client, db_module, original = _client_on(engine)
    try:
        with db_module.db_session() as db:
            db.execute(text("CREATE TABLE orders (id TEXT PRIMARY KEY, status TEXT NOT NULL, "
                            "total_cents INTEGER, currency TEXT, stripe_intent_id TEXT, updated_at TIMESTAMP)"))
            db.execute(text("INSERT INTO orders (id,status,total_cents,currency) VALUES ('ORD-M5','created',5000,'USD')"))
            db.commit()
        targets = ["cancel", "paid", "paid", "cancel"]

        def work(i):
            t = targets[i % len(targets)]
            if t == "cancel":
                return client.post("/api/v1/orders/ORD-M5/cancel", headers=MERCHANT).status_code
            return client.post("/api/v1/orders/ORD-M5/status", headers=MERCHANT,
                               json={"status": "paid"}).status_code

        codes = _fire(4, work)
        assert codes.count(200) == 1, f"exactly one transition may win: {codes}"
        with db_module.db_session() as db:
            assert db.execute(text("SELECT status FROM orders WHERE id='ORD-M5'")).scalar() in ("cancelled", "paid")
    finally:
        db_module.set_engine(original)
        engine.dispose()
        with admin.begin() as c:
            c.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
