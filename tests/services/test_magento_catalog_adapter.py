"""Magento → canonical adapter: proves the seam is platform-blind (same canonical tables, Magento shape)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import catalog_entities as ce
from src.app.services import commerce_catalog as cc
from src.app.services import magento_catalog_adapter as mg


_PRODUCTS = [
    {"id": 5, "sku": "LAP-021", "name": "Widget", "price": 1299,
     "extension_attributes": {"stock_item": {"qty": 4}}},
    {"id": 6, "sku": "LAP-022", "name": "Other", "price": "1499.50",
     "extension_attributes": {"stock_item": {"qty": 9}}},
    {"id": 7, "sku": "", "price": 10},   # no sku → skipped
]


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_price_and_stock_mappers():
    assert mg.price_to_cents(1299) == 129900 and mg.price_to_cents("1499.50") == 149950
    assert mg.stock_qty(_PRODUCTS[0]) == 4 and mg.stock_qty({"sku": "x"}) is None


def test_ingest_writes_canonical_via_magento(db):
    counts = mg.ingest_catalog(db, products=_PRODUCTS, currency="AUD")
    assert counts["prices"] == 2 and counts["inventory"] == 2
    assert cc.retail_unit_cents(db, "LAP-021", channel="magento") == 129900
    assert cc.inventory_for(db, "LAP-021")["on_hand"] == 4
    # the seam: magento product id resolves to the sku
    assert ce.resolve_external(db, platform="magento", entity_type="product", external_id="LAP-021") == "LAP-021"


def test_ingest_is_idempotent(db):
    mg.ingest_catalog(db, products=_PRODUCTS)
    mg.ingest_catalog(db, products=_PRODUCTS)
    assert db.execute(text("SELECT COUNT(*) FROM price_book_entry")).scalar() == 2
    assert db.execute(text("SELECT COUNT(*) FROM inventory_level")).scalar() == 2
