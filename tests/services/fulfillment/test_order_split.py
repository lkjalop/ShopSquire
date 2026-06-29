from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment.order_split import plan_order_split
from src.app.services.supplier_catalog import ensure_supplier_coverage


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _seed_product(db, sku: str, name: str, specs: dict | None = None) -> None:
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, name TEXT, specs TEXT, active INTEGER DEFAULT 1)"
    ))
    db.execute(text(
        "INSERT INTO products (sku, name, specs, active) VALUES (:s, :n, :p, 1)"
    ), {"s": sku, "n": name, "p": json.dumps(specs or {})})


def test_plan_order_split_routes_mixed_lines_to_distinct_suppliers(db):
    _seed_product(db, "GAM-0002", "HP Victus 16 Gaming Laptop with RTX graphics")
    _seed_product(db, "MON-1", "LG UltraGear 34 inch monitor")
    _seed_product(db, "NET-1", "TP-Link Wi-Fi 6 router")
    ensure_supplier_coverage(db)

    plan = plan_order_split(db, lines=[
        {"item_ref": "GAM-0002", "requested_qty": 20, "in_stock": 13},
        {"item_ref": "MON-1", "requested_qty": 30, "in_stock": 5},
        {"item_ref": "NET-1", "requested_qty": 5, "in_stock": 5},
    ])

    assert plan["line_count"] == 3
    assert plan["sourcing_line_count"] == 2
    assert plan["group_count"] == 2
    by_sku = {line["item_ref"]: line for line in plan["lines"]}
    assert by_sku["GAM-0002"]["supplier_ref"] == "SUP-CREATOR"
    assert by_sku["GAM-0002"]["recipient_domain"] == "creatorfleet.example"
    assert by_sku["GAM-0002"]["below_moq"] is True
    assert "25+ units" in by_sku["GAM-0002"]["price_break_advisory"]
    assert by_sku["MON-1"]["supplier_ref"] == "SUP-PERIPH"
    assert by_sku["MON-1"]["recipient_domain"] == "perilink-accessories.example"
    assert by_sku["NET-1"]["status"] == "fillable_from_stock"


def test_plan_order_split_marks_missing_supplier_without_contacting_external_party(db):
    plan = plan_order_split(db, lines=[
        {"item_ref": "UNKNOWN-SKU", "requested_qty": 12, "in_stock": 0},
    ])

    assert plan["line_count"] == 1
    assert plan["sourcing_line_count"] == 0
    assert plan["group_count"] == 0
    assert plan["lines"][0]["status"] == "no_approved_supplier"
    assert plan["lines"][0]["supplier_candidates"] == []
