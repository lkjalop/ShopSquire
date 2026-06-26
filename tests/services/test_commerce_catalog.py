"""Canonical catalog — price_book_entry + inventory_level: idempotent upsert, retail/stock reads, seed."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import commerce_catalog as cc


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


# ── price book ───────────────────────────────────────────────────────────────
def test_price_upsert_is_idempotent_on_key(db):
    assert cc.upsert_price(db, sku="LAP-021", list_cents=120000, source="a")
    cc.upsert_price(db, sku="LAP-021", list_cents=130000, source="b")   # same key → update, not insert
    rows = db.execute(text("SELECT COUNT(*) FROM price_book_entry WHERE sku='LAP-021'")).scalar()
    assert rows == 1
    assert cc.retail_unit_cents(db, "LAP-021") == 130000


def test_retail_prefers_sale_over_list(db):
    cc.upsert_price(db, sku="LAP-021", list_cents=120000, sale_cents=99900)
    assert cc.retail_unit_cents(db, "LAP-021") == 99900


def test_retail_none_when_unpriced(db):
    cc.ensure_tables(db)
    assert cc.retail_unit_cents(db, "NOPE") is None


def test_price_is_channel_and_currency_scoped(db):
    cc.upsert_price(db, sku="LAP-021", list_cents=120000, channel="default", currency="AUD")
    cc.upsert_price(db, sku="LAP-021", list_cents=80000, channel="default", currency="USD")
    assert cc.retail_unit_cents(db, "LAP-021", currency="AUD") == 120000
    assert cc.retail_unit_cents(db, "LAP-021", currency="USD") == 80000


# ── inventory ────────────────────────────────────────────────────────────────
def test_inventory_available_is_on_hand_minus_reserved(db):
    cc.upsert_inventory(db, sku="LAP-021", on_hand=10, reserved=3)
    inv = cc.inventory_for(db, "LAP-021")
    assert inv == {"on_hand": 10, "reserved": 3, "available": 7}


def test_inventory_sums_across_locations(db):
    cc.upsert_inventory(db, sku="LAP-021", on_hand=4, location_id="syd")
    cc.upsert_inventory(db, sku="LAP-021", on_hand=6, reserved=1, location_id="mel")
    inv = cc.inventory_for(db, "LAP-021")
    assert inv["on_hand"] == 10 and inv["available"] == 9
    assert cc.inventory_for(db, "LAP-021", location_id="syd")["on_hand"] == 4


def test_inventory_upsert_idempotent_on_key(db):
    cc.upsert_inventory(db, sku="LAP-021", on_hand=4, location_id="syd")
    cc.upsert_inventory(db, sku="LAP-021", on_hand=2, location_id="syd")  # update same location
    assert db.execute(text("SELECT COUNT(*) FROM inventory_level WHERE sku='LAP-021'")).scalar() == 1
    assert cc.inventory_for(db, "LAP-021")["on_hand"] == 2


def test_inventory_none_when_absent(db):
    cc.ensure_tables(db)
    assert cc.inventory_for(db, "NOPE") is None


# ── seed ─────────────────────────────────────────────────────────────────────
def test_seed_demo_populates_and_is_idempotent(db):
    c = cc.seed_demo(db)
    assert c["prices"] == 3 and c["inventory"] == 3
    assert cc.retail_unit_cents(db, "LAP-021") == 120000
    assert cc.inventory_for(db, "LAP-021")["on_hand"] == 4
    # re-seed updates in place — no row growth
    cc.seed_demo(db)
    assert db.execute(text("SELECT COUNT(*) FROM price_book_entry")).scalar() == 3
