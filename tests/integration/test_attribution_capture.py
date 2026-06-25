"""E1 + E2 end-to-end: an order created from a recommendation is attributed back to it.

Uses an ALIGNED-engine harness (one in-memory engine for seed + request + verify) because the
attribution writes happen during the request (request engine = app.state.engine), which a bare
module-level db_session would not see. Mirrors tests/test_cart_stock_gates.py's proven recipe.

  E1: the order carries the recommendation trace_id (orders.trace_id).
  E2: create_order links the order to the decision that proposed the SKU (conversion_event).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from tests.utils import default_headers


@pytest.fixture()
def stack(monkeypatch):
    monkeypatch.setenv("ATTRIBUTION_ENABLED", "1")
    monkeypatch.setenv("INVENTORY_RESERVATION_ENFORCED", "0")  # skip stock reservation for the test
    monkeypatch.setenv("DISABLE_UI_ROUTES", "1")
    monkeypatch.setenv("AUTO_SEED_CATALOG_ON_START", "0")
    monkeypatch.setenv("AUTO_SEED_GAMING_CATALOG_ON_START", "0")

    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    _dbmod.set_engine(eng)

    from src.app.main import create_app
    app = create_app()
    app.state.engine = eng

    with TestClient(app, headers=default_headers(), raise_server_exceptions=False) as client:
        from src.app.services import attribution
        from src.app.models.db import db_session
        with db_session() as db:
            db.execute(text(
                "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) "
                "VALUES ('ATTR-1','ATTR-1','Attribution Test Laptop',119900,'USD','{}',1)"))
            db.execute(text(
                "INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) "
                "VALUES ('inv-attr-1','ATTR-1',9,'default')"))
            attribution.ensure_tables(db)
            # E0 substrate: a decision that proposed ATTR-1.
            attribution.record_decision(db, trace_id="ATTR-T", decision_id="ATTR-D",
                                        uid_hash="seed", skus=["ATTR-1"])
            db.commit()
        yield client

    _dbmod.engine = orig
    _dbmod.set_engine(orig)


def test_order_attributes_to_decision(stack):
    from src.app.models.db import db_session
    r = stack.post(
        "/api/v1/orders/create",
        json={"uid": "attr-user", "items": [{"sku": "ATTR-1", "quantity": 1}], "trace_id": "ATTR-T"},
    )
    assert r.status_code == 200, r.text
    order_id = r.json()["order_id"]

    with db_session() as db:
        order_trace = db.execute(text("SELECT trace_id FROM orders WHERE id=:o"), {"o": order_id}).fetchone()
        conv = db.execute(
            text("SELECT decision_id, value_cents FROM conversion_event WHERE order_id=:o"),
            {"o": order_id},
        ).fetchone()

    assert order_trace and order_trace[0] == "ATTR-T", "E1: order should carry the trace_id"
    assert conv and conv[0] == "ATTR-D", "E2: order should link to the recorded decision"
    assert int(conv[1] or 0) == 119900, "E2: conversion should carry the order value"
