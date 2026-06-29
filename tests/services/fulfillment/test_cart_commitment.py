"""Phase 2 — cart-commitment materialization: GATE 1 at the buyer's CONFIRM, idempotent on the order id."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import text

from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.cart_commitment import materialize_cases_for_order, order_group_id_for
from src.app.services.supplier_catalog import ensure_supplier_coverage


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _seed_product(db, sku: str, name: str) -> None:
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, name TEXT, specs TEXT, active INTEGER DEFAULT 1)"
    ))
    db.execute(text("INSERT INTO products (sku, name, specs, active) VALUES (:s, :n, :p, 1)"),
               {"s": sku, "n": name, "p": json.dumps({})})


def test_order_group_id_is_deterministic_from_order_id():
    assert order_group_id_for("ORD-1") == "order-ORD-1"
    assert order_group_id_for("  ORD-2  ") == "order-ORD-2"
    assert order_group_id_for("") is None


def test_materialize_creates_grouped_cases_then_is_idempotent(db):
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    lines = [{"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0},   # → SUP-CREATOR
             {"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0}]      # → SUP-PERIPH

    r1 = materialize_cases_for_order(db, order_id="ORD-1", lines=lines, uid="u1")
    assert r1["idempotent"] is False
    assert r1["case_count"] == 2
    assert r1["order_group_id"] == "order-ORD-1"
    # each materialized case waits at GATE 1, no supplier contacted
    for c in r1["cases"]:
        cur = wf.repository.current_version(db, c["case_id"])
        assert cur.state == "AWAITING_BUYER_COMMITMENT"
        assert cur.state_json["order_group_id"] == "order-ORD-1"

    # RE-CONFIRM the same order (double-submit) → SAME cases, NO duplicates (the "two POs" bug killed)
    r2 = materialize_cases_for_order(db, order_id="ORD-1", lines=lines, uid="u1")
    assert r2["idempotent"] is True
    assert r2["case_count"] == 2
    assert {c["case_id"] for c in r2["cases"]} == {c["case_id"] for c in r1["cases"]}


def test_materialize_skips_fully_in_stock_lines(db):
    # a line we can fully fulfil from stock needs no sourcing → no case is created
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    r = materialize_cases_for_order(db, order_id="ORD-2", uid="u1",
                                    lines=[{"item_ref": "MON-1", "requested_qty": 5, "in_stock": 10}])
    assert r["case_count"] == 0 and r["idempotent"] is False


def test_materialize_blank_order_id_is_a_safe_noop(db):
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    r = materialize_cases_for_order(db, order_id="", uid="u1",
                                    lines=[{"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0}])
    assert r["order_group_id"] is None and r["case_count"] == 0
