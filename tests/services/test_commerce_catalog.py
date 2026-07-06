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


def test_batch_available_omits_unknown_skus(db):
    cc.upsert_inventory(db, sku="LAP-021", on_hand=10, reserved=3)   # available 7
    cc.upsert_inventory(db, sku="GAM-1", on_hand=6)                  # available 6
    out = cc.batch_available(db, ["LAP-021", "GAM-1", "UNKNOWN"])
    assert out == {"LAP-021": 7, "GAM-1": 6}  # UNKNOWN omitted (not zeroed) so an overlay can't hide stock


# ── seed ─────────────────────────────────────────────────────────────────────
def test_seed_demo_populates_and_is_idempotent(db):
    c = cc.seed_demo(db)
    assert c["prices"] == 3 and c["inventory"] == 3
    assert cc.retail_unit_cents(db, "LAP-021") == 120000
    assert cc.inventory_for(db, "LAP-021")["on_hand"] == 4
    # re-seed updates in place — no row growth
    cc.seed_demo(db)
    assert db.execute(text("SELECT COUNT(*) FROM price_book_entry")).scalar() == 3


# ── full-catalog backfill (A1 of the competitor-intel plan) ──────────────────
def _seed_products(db, rows):
    db.execute(text("CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, name TEXT, "
                    "price_cents INTEGER, active INTEGER DEFAULT 1)"))
    for sku, cents, active in rows:
        db.execute(text("INSERT INTO products (sku, price_cents, active) VALUES (:s,:c,:a)"),
                   {"s": sku, "c": cents, "a": active})
    db.commit()


def test_backfill_covers_every_active_priced_product(db):
    # Without full price_book coverage, the competitor-undercut LEFT JOIN yields our_price=NULL and the
    # detector silently skips the SKU — so EVERY active priced product must get an 'our retail' row.
    _seed_products(db, [("LAP-A", 100000, 1), ("LAP-B", 200000, 1), ("LAP-OFF", 300000, 0),
                        ("LAP-NOPRICE", None, 1)])
    out = cc.backfill_price_book_from_products(db)
    assert out == {"seen": 2, "written": 2, "skipped": 0}   # inactive + unpriced excluded
    assert cc.retail_unit_cents(db, "LAP-A") == 100000
    assert cc.retail_unit_cents(db, "LAP-B") == 200000
    assert cc.retail_unit_cents(db, "LAP-OFF") is None


def test_backfill_is_idempotent_and_never_clobbers_human_prices(db):
    _seed_products(db, [("LAP-A", 100000, 1), ("LAP-B", 200000, 1)])
    cc.upsert_price(db, sku="LAP-A", list_cents=95000, source="ops_override")  # a human priced this
    out1 = cc.backfill_price_book_from_products(db)
    assert out1["written"] == 1 and out1["skipped"] == 1     # only the gap; the human row untouched
    assert cc.retail_unit_cents(db, "LAP-A") == 95000
    out2 = cc.backfill_price_book_from_products(db)          # re-run → pure no-op
    assert out2["written"] == 0 and out2["skipped"] == 2
    # overwrite refreshes catalog-sourced rows ONLY — the ops override still wins
    db.execute(text("UPDATE products SET price_cents=210000 WHERE sku='LAP-B'")); db.commit()
    out3 = cc.backfill_price_book_from_products(db, overwrite=True)
    assert cc.retail_unit_cents(db, "LAP-B") == 210000
    assert cc.retail_unit_cents(db, "LAP-A") == 95000
