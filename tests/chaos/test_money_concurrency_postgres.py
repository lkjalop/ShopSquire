"""Threaded money-path races against PostgreSQL.

Set TEST_POSTGRES_URL to run this suite. Each test gets an isolated schema and uses a separate
database session per contender; SQLite cannot model these row-lock and unique-index races.
"""
from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def postgres_sessions():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL is required for real PostgreSQL concurrency tests")
    admin_engine = create_engine(url, future=True)
    if admin_engine.dialect.name != "postgresql":
        pytest.skip("TEST_POSTGRES_URL must point to PostgreSQL")
    schema = f"money_race_{uuid.uuid4().hex[:12]}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"}, future=True)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield sessions
    finally:
        engine.dispose()
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _race(work):
    barrier = threading.Barrier(2)

    def contender():
        barrier.wait(timeout=10)
        return work()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return [future.result(timeout=20) for future in (pool.submit(contender), pool.submit(contender))]


def test_refund_slot_has_one_winner(postgres_sessions):
    from src.app.services.payment_ledger import reserve_refund_slot

    def reserve():
        with postgres_sessions() as db:
            won = reserve_refund_slot(db, "refund:req:ORDER-1:0")
            db.commit()
            return won

    assert sorted(_race(reserve)) == [False, True]


def test_inventory_release_credits_stock_once(postgres_sessions):
    from src.app.services.inventory_guard import release_inventory_for_order

    with postgres_sessions.begin() as db:
        db.execute(text("CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT NOT NULL)"))
        db.execute(text("CREATE TABLE inventory (id TEXT PRIMARY KEY, product_id TEXT, stock INT, "
                        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        db.execute(text("CREATE TABLE inventory_reservations (id TEXT PRIMARY KEY, order_id TEXT, "
                        "sku TEXT, qty INT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO products VALUES ('p1', 'SKU-1')"))
        db.execute(text("INSERT INTO inventory (id, product_id, stock) VALUES ('i1', 'p1', 7)"))
        db.execute(text("INSERT INTO inventory_reservations (id, order_id, sku, qty, status) "
                        "VALUES ('r1', 'ORDER-1', 'SKU-1', 3, 'reserved')"))

    def release():
        with postgres_sessions() as db:
            result = release_inventory_for_order(db, order_id="ORDER-1")
            db.commit()
            return result["released"]

    assert sum(_race(release)) == 1
    with postgres_sessions() as db:
        assert db.execute(text("SELECT stock FROM inventory WHERE id='i1'")).scalar_one() == 10
        assert db.execute(text("SELECT status FROM inventory_reservations WHERE id='r1'")).scalar_one() == "released"


def test_cancel_and_mark_paid_cannot_both_win(postgres_sessions):
    with postgres_sessions.begin() as db:
        db.execute(text("CREATE TABLE orders (id TEXT PRIMARY KEY, status TEXT NOT NULL, "
                        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
        db.execute(text("INSERT INTO orders (id, status) VALUES ('ORDER-1', 'created')"))

    targets = iter(("cancelled", "paid"))
    target_lock = threading.Lock()

    def transition():
        with target_lock:
            target = next(targets)
        with postgres_sessions() as db:
            result = db.execute(
                text("UPDATE orders SET status=:target WHERE id='ORDER-1' AND status='created'"),
                {"target": target},
            )
            db.commit()
            return target, int(result.rowcount or 0)

    outcomes = _race(transition)
    assert sorted(rowcount for _, rowcount in outcomes) == [0, 1]
    winner = next(target for target, rowcount in outcomes if rowcount == 1)
    with postgres_sessions() as db:
        assert db.execute(text("SELECT status FROM orders WHERE id='ORDER-1'")).scalar_one() == winner


def test_concurrent_refund_workers_call_provider_once(postgres_sessions):
    from src.app.services import refund_execution as refunds
    with postgres_sessions() as db:
        refunds.open_execution(
            db, order_id="ORDER-R", approval_index=0, amount_cents=2500, currency="USD",
            intent_id="pi_refund_race", idempotency_key="refund:ORDER-R:0")
    calls = {"n": 0}
    lock = threading.Lock()

    def provider(_intent, _amount, _key):
        with lock:
            calls["n"] += 1
        return {"id": "re_race", "status": "pending"}

    def worker():
        with postgres_sessions() as db:
            return refunds.execute_pending(db, refund_fn=provider)

    _race(worker)
    assert calls["n"] == 1
    with postgres_sessions() as db:
        assert db.execute(text(
            "SELECT state FROM refund_executions WHERE order_id='ORDER-R'")) .scalar_one() == refunds.STATE_SUBMITTED
