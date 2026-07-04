"""P0 spine: order -> checkout-initiate -> (webhook) paid -> dispatch queued + tracking assigned
-> carrier webhook -> shipped. Before this wiring: the UI checkout created NO order row, the
public route had no firewall/idempotency, nothing outbound ever assigned a tracking number, and
the carrier webhooks could never match an order. Minimal middleware-free app (same pattern as
test_payments_webhook_failclosed) with an in-memory engine swapped into db_session."""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.app.routers import payments, shipping_webhooks


@pytest.fixture()
def client(monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    _dbmod.set_engine(eng)
    with eng.begin() as c:
        c.execute(text(
            "CREATE TABLE orders (id TEXT PRIMARY KEY, draft_order_id TEXT, customer_id TEXT, "
            "guest_email TEXT, guest_email_hash TEXT, guest_email_encrypted TEXT, total_cents INTEGER, "
            "currency TEXT, status TEXT, trace_id TEXT, stripe_intent_id TEXT, tracking_number TEXT, "
            "carrier TEXT, updated_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("EASYPOST_WEBHOOK_SECRET", raising=False)
    monkeypatch.setattr(payments, "_is_non_dev_env", lambda *_a, **_k: False)
    app = FastAPI()
    app.include_router(payments.router)
    app.include_router(shipping_webhooks.router)
    try:
        yield TestClient(app)
    finally:
        _dbmod.engine = orig
        _dbmod.set_engine(orig)


def test_full_spine_created_paid_dispatched_shipped(client, monkeypatch):
    # P0-A: checkout-initiate creates the REAL order via create_order_core (catalog patched out).
    def fake_core(db, *, uid, items, customer_id=None, guest_email=None, trace_id=None):
        db.execute(text("INSERT INTO orders (id, total_cents, currency, status) "
                        "VALUES ('ORD-SPINE', 20000, 'USD', 'created')"))
        db.commit()
        return {"created": True, "order_id": "ORD-SPINE", "total_cents": 20000, "status": "created"}
    import src.app.routers.orders as orders_mod
    monkeypatch.setattr(orders_mod, "create_order_core", fake_core)

    r = client.post("/api/v1/payments/checkout-initiate",
                    json={"uid": "u-spine", "items": [{"sku": "X", "quantity": 2}], "amount_cents": 1})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["order_id"] == "ORD-SPINE"
    assert d["amount_cents"] == 20000, "server-priced total must beat the client-sent amount"
    intent = d["stripe_intent_id"]
    assert intent and intent.startswith("pi_demo_"), "demo intent must be stamped so the webhook chain is reachable"

    # webhook succeeded -> paid + tracking assigned + dispatch queued (P0-C)
    r2 = client.post("/api/v1/payments/webhook",
                     content=json.dumps({"type": "payment_intent.succeeded", "data": {"object": {"id": intent}}}),
                     headers={"Content-Type": "application/json"})
    assert r2.status_code == 200, r2.text
    from src.app.models.db import db_session
    with db_session() as db:
        row = db.execute(text("SELECT status, tracking_number, carrier FROM orders WHERE id='ORD-SPINE'")).fetchone()
        q = db.execute(text("SELECT status, transition_event FROM outbound_message "
                            "WHERE idempotency_key='dispatch:ORD-SPINE'")).fetchone()
    assert row[0] == "paid" and str(row[1] or "").startswith("TRK-")
    assert q is not None and q[1] == "shipment_plan_created"

    # carrier webhook matches the assigned tracking -> shipped (previously orphaned end-to-end)
    r3 = client.post("/api/v1/shipping/webhook/easypost",
                     content=json.dumps({"description": "tracker.updated",
                                         "result": {"tracking_code": row[1], "status": "in_transit",
                                                    "carrier": "sandbox"}}),
                     headers={"Content-Type": "application/json"})
    assert r3.status_code == 200 and r3.json().get("changed") is True, r3.text
    with db_session() as db:
        st = db.execute(text("SELECT status FROM orders WHERE id='ORD-SPINE'")).scalar()
    assert st == "shipped"


def test_checkout_initiate_idempotency_409_on_duplicate(client):
    r1 = client.post("/api/v1/payments/checkout-initiate", json={"order_id": "ORD-DUP", "amount_cents": 500})
    assert r1.status_code == 200
    r2 = client.post("/api/v1/payments/checkout-initiate", json={"order_id": "ORD-DUP", "amount_cents": 500})
    assert r2.status_code == 409


def test_no_items_no_order_still_demo_confirms(client):
    r = client.post("/api/v1/payments/checkout-initiate", json={"amount_cents": 900})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "demo_confirmed" and d["stripe_intent_id"] is None
    assert str(d["order_id"]).startswith("DEMO-")
