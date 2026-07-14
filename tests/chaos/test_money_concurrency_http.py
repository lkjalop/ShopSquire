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
        results = _fire(5, lambda _i: client.post("/api/v1/payments/webhook",
                                                  data=json.dumps(evt)).json().get("duplicate") is True)
        assert results.count(False) == 1, f"exactly one delivery processes: {results}"
        assert results.count(True) == 4
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
