"""Unified customer purchases + tracking — the customer-facing read that unions consumer orders and
procurement cases into one timeline, and a per-order tracking read scoped to the requester."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def db():
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng; _dbmod.set_engine(eng)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT, guest_email_hash TEXT, "
                       "total_cents INTEGER, currency TEXT, status TEXT, tracking_number TEXT, carrier TEXT, "
                       "created_at TEXT, updated_at TEXT)"))
        c.execute(text("CREATE TABLE order_sessions (id TEXT PRIMARY KEY, uid TEXT, order_id TEXT, "
                       "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    from src.app.models.db import db_session
    with db_session() as s:
        yield s
    _dbmod.engine = orig; _dbmod.set_engine(orig)


def _seed_order(db, oid, uid, *, status="shipped", tracking="TRK-1", total=95900, created="2026-07-05T10:00:00"):
    db.execute(text("INSERT INTO orders (id, customer_id, total_cents, currency, status, tracking_number, carrier, created_at) "
                    "VALUES (:o,:c,:t,'USD',:s,:tn,'sandbox',:cr)"),
               {"o": oid, "c": uid, "t": total, "s": status, "tn": tracking, "cr": created})
    db.execute(text("INSERT INTO order_sessions (id, uid, order_id) VALUES (:i,:u,:o)"),
               {"i": oid+"-s", "u": uid, "o": oid})
    db.commit()


def test_unified_purchases_includes_consumer_orders(db, monkeypatch):
    # no procurement cases → just the consumer orders, newest first
    import src.app.services.account_purchases as ap
    monkeypatch.setattr(ap, "_procurement_entries", lambda db, oid: [])
    _seed_order(db, "O-1", "u1", created="2026-07-01T10:00:00")
    _seed_order(db, "O-2", "u1", created="2026-07-05T10:00:00")
    items = ap.unified_purchases(db, uid="u1")
    assert [i["id"] for i in items] == ["O-2", "O-1"]  # newest first
    assert all(i["kind"] == "order" for i in items)
    assert items[0]["tracking_number"] == "TRK-1"


def test_unified_purchases_unions_procurement(db, monkeypatch):
    import src.app.services.account_purchases as ap
    monkeypatch.setattr(ap, "_procurement_entries", lambda db, oid: [
        {"kind": "procurement", "id": "CASE-9", "order_id": oid, "status": "AWAITING_BUYER_COMMITMENT",
         "supplier_domain": "vendor.com", "created_at": "2026-07-06T10:00:00", "sort_key": "2026-07-06T10:00:00"}])
    _seed_order(db, "O-1", "u1", created="2026-07-05T10:00:00")
    items = ap.unified_purchases(db, uid="u1")
    kinds = [i["kind"] for i in items]
    assert "order" in kinds and "procurement" in kinds
    # procurement case (2026-07-06) sorts newest, above the order (2026-07-05)
    assert items[0]["kind"] == "procurement" and items[0]["supplier_domain"] == "vendor.com"


def test_order_tracking_scoped_to_owner(db):
    from src.app.services.account_purchases import order_tracking
    _seed_order(db, "O-7", "owner-uid")
    ok = order_tracking(db, "O-7", uid="owner-uid")
    assert ok and ok["tracking_number"] == "TRK-1" and ok["status"] == "shipped"
    # a different uid must NOT see it
    assert order_tracking(db, "O-7", uid="stranger-uid") is None
    # by customer_id owner
    assert order_tracking(db, "O-7", customer_id="owner-uid")["order_id"] == "O-7"
