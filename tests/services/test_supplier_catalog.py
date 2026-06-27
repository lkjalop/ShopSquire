"""A1 — supplier catalog schema + seed: the default draft path resolves an approved supplier."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.supplier_catalog import (
    DEMO_SKUS,
    cheapest_wholesale_cents,
    domain_for_supplier,
    ensure_tables,
    seed_demo,
)


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_seed_is_idempotent_and_maps_skus(db):
    c1 = seed_demo(db, skus=["LAP-021"])
    assert c1["suppliers"] == 2 and c1["domains"] == 2 and c1["products"] == 2
    c2 = seed_demo(db, skus=["LAP-021"])  # re-run inserts nothing
    assert c2 == {"suppliers": 0, "products": 0, "domains": 0}


def test_domain_for_supplier_from_allowlist(db):
    seed_demo(db, skus=["LAP-021"])
    assert domain_for_supplier(db, "SUP-7") == "approved-supplier.example"
    assert domain_for_supplier(db, "nope") is None


def test_cheapest_wholesale_cents_picks_lowest(db):
    seed_demo(db, skus=["LAP-021"])  # SUP-7=1115.00, SUP-3=1180.00 → cheapest = 111500c
    assert cheapest_wholesale_cents(db, "LAP-021") == 111500
    assert cheapest_wholesale_cents(db, "no-such-sku") is None


def test_seed_demo_vendor_contacts_registers_verified_email():
    # the live-packet fix: seed a KYV vendor so the draft resolves a CONTACT EMAIL, not the bare domain
    from src.app.security.kyv_registry import lookup_vendor_by_domain
    from src.app.services.supplier_catalog import seed_demo_vendor_contacts
    seed_demo_vendor_contacts()
    v = lookup_vendor_by_domain(tenant_id="default", domain="approved-supplier.example")
    assert v and v.get("contact_email") == "orders@approved-supplier.example"
    assert seed_demo_vendor_contacts() == 0  # idempotent — re-run registers nothing new


def test_ranking_query_shape_resolves_two_suppliers(db):
    # the exact join inventory_agent._get_best_supplier runs must return the seeded suppliers
    seed_demo(db, skus=["LAP-021"])
    rows = db.execute(text("SELECT s.id, s.unit_cost, s.lead_time_days FROM suppliers s "
                           "JOIN supplier_products sp ON sp.supplier_id = s.id WHERE sp.sku = :k"),
                      {"k": "LAP-021"}).fetchall()
    assert {r[0] for r in rows} == {"SUP-7", "SUP-3"}


def test_default_draft_path_resolves_seeded_supplier():
    """Integration: with the catalog seeded in the APP db, build_draft's DEFAULT path (no injected
    rank/allowlist fns) resolves the winning approved supplier — the live happy-path is unblocked."""
    from src.app.models.db import db_session
    from src.app.services.fulfillment.draft import build_draft
    with db_session() as db:
        seed_demo(db, skus=["LAP-021"])
    with db_session() as db:
        draft = build_draft(db, item_ref="LAP-021", quantity=6, case_ref="FC-IT-1", estimated_value_cents=669000)
    assert draft is not None, "default draft path still resolves NO supplier — seed/enrichment broken"
    assert draft.recipient_domain == "approved-supplier.example"  # SUP-7 wins (cheaper/faster/reliable)
    assert draft.content_hash and "purchase order" in draft.body.lower()
    assert any("allowlist" in r for r in draft.rationale)
