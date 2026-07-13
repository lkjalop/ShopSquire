"""P1: append-only payment ledger + governed refunds (GATE-2 mold).

Payment state used to be one mutable string on orders; refunds could only be OBSERVED via
charge.refunded. Now every event appends to payment_transactions, refunds are a two-step
(merchant requests -> HUMAN owner approves) and the settlement webhook reconciles against the
ledger. Minimal middleware-free app + in-memory engine (spine-test pattern)."""
from __future__ import annotations

import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.app.routers import payments

MERCHANT = {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}
OWNER = {"x-api-key": os.getenv("OWNER_API_KEY", "local-owner-key")}


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
    monkeypatch.setattr(payments, "_is_non_dev_env", lambda *_a, **_k: False)
    app = FastAPI()
    app.include_router(payments.router)
    try:
        yield TestClient(app)
    finally:
        _dbmod.engine = orig
        _dbmod.set_engine(orig)


def _seed_paid_order(oid="ORD-L1", total=50000, intent="pi_demo_ledger1"):
    from src.app.models.db import db_session
    from src.app.services.payment_ledger import KIND_PAYMENT_SUCCEEDED, record_txn
    with db_session() as db:
        db.execute(text("INSERT INTO orders (id, total_cents, currency, status, stripe_intent_id) "
                        "VALUES (:o, :t, 'USD', 'paid', :i)"), {"o": oid, "t": total, "i": intent})
        record_txn(db, order_id=oid, kind=KIND_PAYMENT_SUCCEEDED, intent_id=intent,
                   amount_cents=total, provider="demo")
        db.commit()


def test_paid_webhook_appends_succeeded_and_dispatch_events(client, monkeypatch):
    def fake_core(db, **_kw):
        db.execute(text("INSERT INTO orders (id, total_cents, currency, status) "
                        "VALUES ('ORD-LW', 12300, 'USD', 'created')"))
        db.commit()
        return {"created": True, "order_id": "ORD-LW", "total_cents": 12300}
    import src.app.routers.orders as orders_mod
    monkeypatch.setattr(orders_mod, "create_order_core", fake_core)
    d = client.post("/api/v1/payments/checkout-initiate",
                    json={"uid": "u", "items": [{"sku": "X", "quantity": 1}]}).json()
    client.post("/api/v1/payments/webhook",
                content=json.dumps({"type": "payment_intent.succeeded",
                                    "data": {"object": {"id": d["stripe_intent_id"]}}}),
                headers={"Content-Type": "application/json"})
    from src.app.models.db import db_session
    from src.app.services.payment_ledger import ledger_for_order
    with db_session() as db:
        kinds = [e["kind"] for e in ledger_for_order(db, "ORD-LW")]
    assert kinds == ["intent_created", "payment_succeeded", "dispatch_queued"]


def test_refund_two_step_then_settlement_reconciles(client):
    _seed_paid_order()
    r1 = client.post("/api/v1/payments/refunds/request", headers=MERCHANT,
                     json={"order_id": "ORD-L1", "amount_cents": 20000, "reason": "damaged item"})
    assert r1.status_code == 200 and r1.json()["approval_required"] is True
    # one open request at a time
    assert client.post("/api/v1/payments/refunds/request", headers=MERCHANT,
                       json={"order_id": "ORD-L1", "amount_cents": 100}).status_code == 409
    # merchant cannot approve — HUMAN owner only (GATE-2 invariant)
    assert client.post("/api/v1/payments/refunds/ORD-L1/approve", headers=MERCHANT).status_code == 403
    r2 = client.post("/api/v1/payments/refunds/ORD-L1/approve", headers=OWNER)
    assert r2.status_code == 200 and r2.json()["amount_cents"] == 20000
    assert client.post("/api/v1/payments/refunds/ORD-L1/approve", headers=OWNER).status_code == 409
    # provider settles -> refund_settled appended, order returned, approved covers settled
    client.post("/api/v1/payments/webhook",
                content=json.dumps({"type": "charge.refunded",
                                    "data": {"object": {"id": "ch_1", "payment_intent": "pi_demo_ledger1",
                                                        "amount_refunded": 20000}}}),
                headers={"Content-Type": "application/json"})
    from src.app.models.db import db_session
    from src.app.services.payment_ledger import refund_state
    with db_session() as db:
        st = db.execute(text("SELECT status FROM orders WHERE id='ORD-L1'")).scalar()
        state = refund_state(db, "ORD-L1")
    assert st == "returned"
    assert state == {"captured_cents": 50000, "requested_cents": 20000, "approved_cents": 20000,
                     "settled_cents": 20000, "open_request": False, "requests": 1, "approvals": 1}


def test_refund_guards(client):
    _seed_paid_order(oid="ORD-L2", total=1000, intent="pi_demo_l2")
    # over-amount refused
    assert client.post("/api/v1/payments/refunds/request", headers=MERCHANT,
                       json={"order_id": "ORD-L2", "amount_cents": 5000}).status_code == 422
    # unknown order
    assert client.post("/api/v1/payments/refunds/request", headers=MERCHANT,
                       json={"order_id": "NOPE", "amount_cents": 1}).status_code == 404
    # approve with nothing open
    assert client.post("/api/v1/payments/refunds/ORD-L2/approve", headers=OWNER).status_code == 409
    # unrefundable status
    from src.app.models.db import db_session
    with db_session() as db:
        db.execute(text("INSERT INTO orders (id, total_cents, currency, status) VALUES ('ORD-L3', 900, 'USD', 'created')"))
        db.commit()
    assert client.post("/api/v1/payments/refunds/request", headers=MERCHANT,
                       json={"order_id": "ORD-L3", "amount_cents": 900}).status_code == 409


def test_refund_approve_executes_via_stripe_when_live(client, monkeypatch):
    """Live Stripe key + real intent → refund_approve EXECUTES stripe.Refund.create (not just
    authorizes). Idempotency key prevents a double refund on retry."""
    _seed_paid_order(oid="ORD-EXEC", total=40000, intent="pi_real_live1")
    r1 = client.post("/api/v1/payments/refunds/request", headers=MERCHANT,
                     json={"order_id": "ORD-EXEC", "amount_cents": 40000, "reason": "damaged"})
    assert r1.status_code == 200

    calls = []

    class _FakeStripeClient:
        def __init__(self, key):
            self.key = key
        def create_refund(self, *, payment_intent_id, amount_cents=None, reason=None, idempotency_key=None):
            calls.append({"pi": payment_intent_id, "amount": amount_cents, "idem": idempotency_key})
            return {"id": "re_123", "payment_intent": payment_intent_id, "amount": amount_cents,
                    "currency": "usd", "status": "succeeded"}

    import src.app.routers.payments as pay
    monkeypatch.setattr(pay, "StripeClient", _FakeStripeClient)
    monkeypatch.setattr(pay, "_stripe_key_live", lambda k: True)
    monkeypatch.setattr(pay, "get_settings", lambda: type("S", (), {"stripe_api_key": "sk_live_real"})())

    r2 = client.post("/api/v1/payments/refunds/ORD-EXEC/approve", headers=OWNER)
    assert r2.status_code == 200, r2.text
    d = r2.json()
    assert d["status"] == "refund_executed" and d["provider_execution"] == "stripe"
    assert d["provider_refund_id"] == "re_123"
    assert calls == [{"pi": "pi_real_live1", "amount": 40000, "idem": "refund:ORD-EXEC:0"}]


def test_refund_approve_demo_intent_stays_manual(client, monkeypatch):
    """A demo intent (pi_demo_*) has no provider charge → approval stays manual/webhook even with a
    live key. Never calls create_refund."""
    _seed_paid_order(oid="ORD-DEMO", total=1000, intent="pi_demo_x1")
    client.post("/api/v1/payments/refunds/request", headers=MERCHANT,
                json={"order_id": "ORD-DEMO", "amount_cents": 1000})
    import src.app.routers.payments as pay
    monkeypatch.setattr(pay, "_stripe_key_live", lambda k: True)
    monkeypatch.setattr(pay, "get_settings", lambda: type("S", (), {"stripe_api_key": "sk_live_real"})())

    class _Boom:
        def __init__(self, k): raise AssertionError("must not construct StripeClient for a demo intent")
    monkeypatch.setattr(pay, "StripeClient", _Boom)

    r = client.post("/api/v1/payments/refunds/ORD-DEMO/approve", headers=OWNER)
    assert r.status_code == 200 and r.json()["provider_execution"] == "manual_or_webhook"
