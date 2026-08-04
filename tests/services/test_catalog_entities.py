"""Canonical identity + integration seam — product / variant / external_ref upsert, lookup, resolve."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import catalog_entities as ce


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_variant_upsert_idempotent_and_lookup(db):
    assert ce.upsert_variant(db, sku="LAP-021", product_id="p1", attributes={"color": "black"})
    ce.upsert_variant(db, sku="LAP-021", product_id="p1", attributes={"color": "silver"})  # update
    assert db.execute(text("SELECT COUNT(*) FROM variant WHERE sku='LAP-021'")).scalar() == 1
    v = ce.variant_by_sku(db, "LAP-021")
    assert v["product_id"] == "p1" and v["attributes"]["color"] == "silver"


def test_product_attributes_round_trip(db):
    ce.upsert_product(db, product_id="p1", title="Widget", brand="Acme",
                      attributes={"warranty_months": 24})
    row = db.execute(text("SELECT title, brand, attributes_json FROM product WHERE id='p1'")).fetchone()
    assert row[0] == "Widget" and row[1] == "Acme" and "warranty_months" in row[2]


def test_variant_lookup_missing_is_none(db):
    ce.ensure_tables(db)
    assert ce.variant_by_sku(db, "NOPE") is None


# ── external_ref (the integration seam) ──────────────────────────────────────
def test_external_ref_resolve(db):
    ce.upsert_external_ref(db, platform="shopify", entity_type="inventory_item", external_id="ii-1",
                           entity_id="LAP-021")
    assert ce.resolve_external(db, platform="shopify", entity_type="inventory_item", external_id="ii-1") == "LAP-021"
    # different platform / unknown id → None
    assert ce.resolve_external(db, platform="magento", entity_type="inventory_item", external_id="ii-1") is None


def test_external_ref_is_idempotent_and_remaps(db):
    ce.upsert_external_ref(db, platform="shopify", entity_type="product", external_id="9", entity_id="A")
    ce.upsert_external_ref(db, platform="shopify", entity_type="product", external_id="9", entity_id="B")  # remap
    assert db.execute(text("SELECT COUNT(*) FROM external_ref WHERE external_id='9'")).scalar() == 1
    assert ce.resolve_external(db, platform="shopify", entity_type="product", external_id="9") == "B"


def test_same_external_id_distinct_per_platform(db):
    ce.upsert_external_ref(db, platform="shopify", entity_type="product", external_id="100", entity_id="SH")
    ce.upsert_external_ref(db, platform="magento", entity_type="product", external_id="100", entity_id="MG")
    assert ce.resolve_external(db, platform="shopify", entity_type="product", external_id="100") == "SH"
    assert ce.resolve_external(db, platform="magento", entity_type="product", external_id="100") == "MG"
