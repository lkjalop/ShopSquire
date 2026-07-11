"""T0 read-model facade: one API over legacy products and canonical variant tables.
Pins mode selection, both adapters, dual-mode divergence, the coverage report (the
CATALOG_READ_MODEL=canonical promotion gate), and the legacy→canonical backfill loop."""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.catalog_read_model import (
    VariantView,
    backfill_canonical_from_legacy,
    coverage_report,
    get_variant,
    read_model_mode,
    search_variants,
)


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Session = sessionmaker(bind=eng)
    s = Session()
    s.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "price_cents INT NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', image_url TEXT, specs TEXT, "
        "product_type TEXT, brand TEXT, category TEXT, attributes TEXT, active INTEGER DEFAULT 1, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.execute(text(
        "CREATE TABLE inventory (id TEXT PRIMARY KEY, product_id TEXT NOT NULL, stock INT NOT NULL, "
        "warehouse TEXT DEFAULT 'default', updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, currency, specs, product_type, brand, category) "
        "VALUES ('p1', 'LAP-1', 'Dell G16 Gaming Laptop', 169900, 'USD', "
        "'{\"ram_gb\": 16, \"gpu\": \"RTX 4060\"}', 'laptop', 'Dell', 'computers')"))
    s.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, currency, specs, product_type, brand, category) "
        "VALUES ('p2', 'BAG-1', 'Laptop Bag 16in', 4900, 'USD', '{}', 'bag', 'Targus', 'accessories')"))
    s.execute(text("INSERT INTO inventory (id, product_id, stock) VALUES ('i1', 'p1', 7)"))
    yield s
    s.close()


def _seed_canonical(db, *, price_cents=169900):
    from src.app.services.catalog_entities import upsert_product, upsert_variant
    from src.app.services.commerce_catalog import upsert_inventory, upsert_price
    upsert_product(db, product_id="p1", title="Dell G16 Gaming Laptop", brand="Dell", category="computers")
    upsert_variant(db, sku="LAP-1", product_id="p1",
                   attributes={"product_type": "laptop", "specs": {"ram_gb": 16}})
    upsert_price(db, sku="LAP-1", list_cents=price_cents, currency="USD", channel="default")
    upsert_inventory(db, sku="LAP-1", on_hand=7)


def test_default_mode_is_legacy(monkeypatch):
    monkeypatch.delenv("CATALOG_READ_MODEL", raising=False)
    monkeypatch.setattr("src.app.config.get_settings", lambda: (_ for _ in ()).throw(RuntimeError), raising=False)
    assert read_model_mode() == "legacy"


def test_legacy_get_and_stock(db):
    v = get_variant(db, "LAP-1", mode="legacy")
    assert isinstance(v, VariantView) and v.source == "legacy"
    assert v.title == "Dell G16 Gaming Laptop" and v.price_cents == 169900
    assert v.specs.get("ram_gb") == 16 and v.stock == 7
    assert v.stock_source == "legacy_inventory" and v.stock_as_of  # provenance + freshness


def test_canonical_stock_provenance(db):
    _seed_canonical(db)
    v = get_variant(db, "LAP-1", mode="canonical")
    assert v.stock == 7 and v.stock_source == "inventory_level" and v.stock_as_of
    # no stock rows -> provenance honestly absent, never fabricated
    from src.app.services.catalog_entities import upsert_variant
    upsert_variant(db, sku="NOSTOCK-1", product_id="p9")
    v2 = get_variant(db, "NOSTOCK-1", mode="canonical")
    assert v2.stock is None and v2.stock_source is None and v2.stock_as_of is None


def test_legacy_search_filters(db):
    got = search_variants(db, text_query="laptop", max_price_cents=100000, mode="legacy")
    assert [v.sku for v in got] == ["BAG-1"]  # LAP-1 excluded by price cap
    got = search_variants(db, brand="Dell", mode="legacy")
    assert [v.sku for v in got] == ["LAP-1"]


def test_canonical_adapter_roundtrip(db):
    _seed_canonical(db)
    v = get_variant(db, "LAP-1", mode="canonical")
    assert v is not None and v.source == "canonical"
    assert v.brand == "Dell" and v.price_cents == 169900 and v.stock == 7
    assert v.product_type == "laptop"
    got = search_variants(db, brand="Dell", mode="canonical")
    assert [x.sku for x in got] == ["LAP-1"]


def test_canonical_missing_tables_fail_empty():
    eng = create_engine("sqlite://")
    s = sessionmaker(bind=eng)()
    assert get_variant(s, "LAP-1", mode="canonical") is None
    assert search_variants(s, text_query="laptop", mode="canonical") == []
    s.close()


def test_dual_mode_serves_legacy(db):
    _seed_canonical(db, price_cents=159900)  # canonical drifted cheaper
    v = get_variant(db, "LAP-1", mode="dual")
    assert v.source == "legacy" and v.price_cents == 169900  # legacy stays authoritative


def test_coverage_report_quantifies_gap(db):
    rep = coverage_report(db)
    assert rep["legacy_count"] == 2 and rep["canonical_count"] == 0
    assert rep["missing_in_canonical_count"] == 2
    _seed_canonical(db, price_cents=159900)
    rep = coverage_report(db)
    assert rep["overlap"] == 1 and rep["missing_in_canonical_count"] == 1
    assert rep["price_drift_count"] == 1
    assert rep["price_drift"][0] == {"sku": "LAP-1", "legacy": 169900, "canonical": 159900}


def test_coverage_reports_unclassified_active(db):
    """The census-3 root cause as a permanent metric: active SKUs without classification
    rows are invisible to taxonomy retrieval — must be counted, never silently zero."""
    rep = coverage_report(db)
    assert rep["unclassified_active_count"] == 2   # both fixture SKUs unclassified
    from src.app.services.taxonomy_registry import upsert_classification
    upsert_classification(db, sku="LAP-1", node_handle="el-6-6", source="test")
    assert coverage_report(db)["unclassified_active_count"] == 1


def test_backfill_reaches_parity(db):
    stats = backfill_canonical_from_legacy(db, commit=False)
    assert stats["variants"] == 2 and stats["prices"] == 2
    rep = coverage_report(db)
    assert rep["missing_in_canonical_count"] == 0
    assert rep["price_drift_count"] == 0  # backfilled price matches legacy
    v = get_variant(db, "LAP-1", mode="canonical")
    assert v is not None and v.price_cents == 169900 and v.specs.get("ram_gb") == 16
    # stock deliberately NOT backfilled (inventory_level owns stock)
    assert v.stock is None
    # idempotent: run again, still parity
    backfill_canonical_from_legacy(db, commit=False)
    assert coverage_report(db)["missing_in_canonical_count"] == 0
