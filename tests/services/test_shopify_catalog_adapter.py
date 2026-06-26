"""Shopify → canonical adapter: decimal-string prices → cents, variants → price_book, inventory_levels
keyed back to sku, and an idempotent end-to-end ingest."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import commerce_catalog as cc
from src.app.services import shopify_catalog_adapter as sh


# sample Shopify shapes (trimmed to the fields the adapter reads)
_PRODUCTS = [
    {"id": 111, "title": "Widget", "variants": [
        {"id": 1, "sku": "LAP-021", "price": "1299.00", "inventory_item_id": "ii-1"},
        {"id": 2, "sku": "LAP-022", "price": "1,499.50", "inventory_item_id": "ii-2"},
    ]},
    {"id": 222, "title": "Other", "variants": [
        {"id": 3, "sku": "", "price": "10.00", "inventory_item_id": "ii-3"},   # no sku → skipped
    ]},
]
_LEVELS = [
    {"inventory_item_id": "ii-1", "location_id": "loc-syd", "available": 4},
    {"inventory_item_id": "ii-2", "location_id": "loc-syd", "available": 9},
    {"inventory_item_id": "ii-x", "location_id": "loc-syd", "available": 99},  # unknown item → skipped
]


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


# ── pure mappers ─────────────────────────────────────────────────────────────
def test_price_to_cents_parses_decimal_and_commas():
    assert sh.price_to_cents("1299.00") == 129900
    assert sh.price_to_cents("1,499.50") == 149950
    assert sh.price_to_cents("bad") is None and sh.price_to_cents(None) is None


def test_variants_to_prices_skips_no_sku():
    rows = sh.variants_to_prices(_PRODUCTS[0])
    assert {r["sku"] for r in rows} == {"LAP-021", "LAP-022"}
    assert sh.variants_to_prices(_PRODUCTS[1]) == []  # the empty-sku variant is dropped


def test_inventory_item_to_sku_map():
    m = sh.inventory_item_to_sku(_PRODUCTS)
    assert m == {"ii-1": "LAP-021", "ii-2": "LAP-022"}


# ── end-to-end ingest ────────────────────────────────────────────────────────
def test_ingest_writes_canonical_prices_and_stock(db):
    counts = sh.ingest_shop_catalog(db, products=_PRODUCTS, inventory_levels=_LEVELS,
                                    tenant_id="default", currency="AUD")
    assert counts["prices"] == 2 and counts["inventory"] == 2   # LAP-021 + LAP-022 (unknown item skipped)
    assert cc.retail_unit_cents(db, "LAP-021", channel="shopify") == 129900
    assert cc.inventory_for(db, "LAP-021")["available"] == 4


def test_ingest_is_idempotent(db):
    sh.ingest_shop_catalog(db, products=_PRODUCTS, inventory_levels=_LEVELS)
    sh.ingest_shop_catalog(db, products=_PRODUCTS, inventory_levels=_LEVELS)  # re-sync
    assert db.execute(text("SELECT COUNT(*) FROM price_book_entry")).scalar() == 2
    assert db.execute(text("SELECT COUNT(*) FROM inventory_level")).scalar() == 2
