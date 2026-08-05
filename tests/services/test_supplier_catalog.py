"""A1 — supplier catalog schema + seed: the default draft path resolves an approved supplier."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.supplier_catalog import (
    all_catalog_skus,
    cheapest_wholesale_cents,
    domain_for_supplier,
    ensure_supplier_coverage,
    best_supplier_cost,
    seed_demo,
    seed_demo_supplier_offers,
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


def test_demo_supplier_offers_are_per_sku_tenant_currency_and_simulation_only(db):
    db.execute(text(
        "CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, price_cents INT, "
        "currency TEXT, specs TEXT, active INTEGER DEFAULT 1)"
    ))
    db.execute(text(
        "INSERT INTO products VALUES "
        "('LAP-A','Work Laptop',100000,'AUD','{}',1),"
        "('LAP-B','Creator Laptop',200000,'AUD','{}',1)"
    ))
    db.commit()
    ensure_supplier_coverage(db)

    first = seed_demo_supplier_offers(db, tenant_id="tenant-a")
    second = seed_demo_supplier_offers(db, tenant_id="tenant-a")

    assert first["offers"] == 2
    assert second["offers"] == 0
    a = best_supplier_cost(db, "LAP-A", tenant_id="tenant-a", currency="AUD")
    b = best_supplier_cost(db, "LAP-B", tenant_id="tenant-a", currency="AUD")
    assert a and b
    assert a["unit_cost_cents"] != b["unit_cost_cents"]
    assert a["cost_basis"] == "demo_estimated_landed_cost"
    assert a["simulation_only"] is True
    assert a["currency"] == "AUD"
    assert best_supplier_cost(db, "LAP-A", tenant_id="tenant-b", currency="AUD") is None
    assert best_supplier_cost(db, "LAP-A", tenant_id="tenant-a", currency="USD") is None


def test_supplier_offer_text_validity_is_evaluated_portably(db):
    db.execute(text(
        "CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, price_cents INT, "
        "currency TEXT, specs TEXT, active INTEGER DEFAULT 1)"
    ))
    db.execute(text(
        "INSERT INTO products VALUES ('LAP-A','Work Laptop',100000,'AUD','{}',1)"
    ))
    db.commit()
    ensure_supplier_coverage(db)
    seed_demo_supplier_offers(db, tenant_id="tenant-a")
    db.execute(text(
        "UPDATE supplier_offer SET effective_to='2020-01-01T00:00:00+00:00' "
        "WHERE tenant_id='tenant-a' AND sku='LAP-A'"
    ))
    db.commit()

    assert best_supplier_cost(db, "LAP-A", tenant_id="tenant-a", currency="AUD") is None


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


def _seed_products(db, skus):
    db.execute(text("CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, active INTEGER DEFAULT 1)"))
    for sku in skus:
        db.execute(text("INSERT INTO products (sku, active) VALUES (:k, 1)"), {"k": sku})
    db.commit()


def test_ensure_supplier_coverage_tracks_the_catalog(db):
    # the NO_APPROVED_SUPPLIER fix: coverage must follow the catalog, not a hardcoded shortlist. A SKU the
    # recommender actually returns (GAM-0002) is NOT in DEMO_SKUS, yet must resolve an approved supplier.
    _seed_products(db, ["GAM-0002", "LAP-0021"])
    assert "GAM-0002" in all_catalog_skus(db)
    ensure_supplier_coverage(db)
    # The routed demo model keeps old broad fallback rows inactive and maps each SKU to its likely supplier.
    rows = db.execute(text("SELECT s.id FROM suppliers s JOIN supplier_products sp ON sp.supplier_id = s.id "
                           "WHERE sp.sku = :k AND COALESCE(sp.active,1)=1"),
                      {"k": "GAM-0002"}).fetchall()
    assert {r[0] for r in rows} == {"SUP-CREATOR"}
    lap_rows = db.execute(text("SELECT s.id FROM suppliers s JOIN supplier_products sp ON sp.supplier_id = s.id "
                               "WHERE sp.sku = :k AND COALESCE(sp.active,1)=1"),
                          {"k": "LAP-0021"}).fetchall()
    assert {r[0] for r in lap_rows} == {"SUP-BIZ"}
    assert cheapest_wholesale_cents(db, "GAM-0002") == 126000  # economics fallback resolves too


def test_ensure_supplier_coverage_is_idempotent(db):
    _seed_products(db, ["GAM-0002"])
    ensure_supplier_coverage(db)
    again = ensure_supplier_coverage(db)  # re-run inserts nothing
    # subset assertion (robust to added keys like 'channels'): idempotency = every insert-count 0
    assert again["suppliers"] == 0 and again["products"] == 0 and again["domains"] == 0
    assert all(v == 0 for v in again.values())


def test_ensure_supplier_coverage_routes_mixed_catalog_to_distinct_suppliers(db):
    db.execute(text(
        "CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, specs TEXT, active INTEGER DEFAULT 1)"
    ))
    rows = [
        ("LAP-BIZ1", "Dell Latitude 15 business laptop", {}),
        ("LAP-GAME1", "HP Victus 16 Gaming Laptop with RTX graphics", {}),
        ("LAP-APPLE1", "Apple MacBook Air 13-inch", {}),
        ("MON-1", "LG UltraGear 34 inch monitor", {}),
        ("NET-1", "TP-Link Wi-Fi 6 router", {}),
    ]
    for sku, name, specs in rows:
        db.execute(text("INSERT INTO products (sku, name, specs, active) VALUES (:s, :n, :p, 1)"),
                   {"s": sku, "n": name, "p": json.dumps(specs)})
    db.commit()

    ensure_supplier_coverage(db)

    got = dict(db.execute(text(
        "SELECT sp.sku, sp.supplier_id FROM supplier_products sp "
        "WHERE sp.sku IN ('LAP-BIZ1','LAP-GAME1','LAP-APPLE1','MON-1','NET-1') "
        "AND COALESCE(sp.active,1)=1 ORDER BY sp.sku"
    )).fetchall())
    assert got == {
        "LAP-APPLE1": "SUP-APPLE",
        "LAP-BIZ1": "SUP-BIZ",
        "LAP-GAME1": "SUP-CREATOR",
        "MON-1": "SUP-PERIPH",
        "NET-1": "SUP-OFFICE",
    }


def test_register_or_backfill_vendor_fills_missing_contact():
    # item-2 fix: an existing vendor row WITHOUT a contact email must get it backfilled (not skipped),
    # else the draft keeps resolving the bare domain. Must NOT create a duplicate insert.
    from src.app.services.supplier_catalog import _register_or_backfill_vendor
    calls = {}

    def lookup(*, tenant_id, domain):
        return {"contact_email": ""}  # exists, contact missing

    def register(**k):
        calls["register"] = k
        return {"ok": True}

    def backfill(*, tenant_id, domain, contact_email):
        calls["backfill"] = (domain, contact_email)
        return True
    assert _register_or_backfill_vendor(lookup, register, backfill,
                                        tenant_id="default", name="X", domain="d.example",
                                        email="e@d.example") is True
    assert calls.get("backfill") == ("d.example", "e@d.example")
    assert "register" not in calls  # existing row → backfill, never a duplicate insert


def test_register_or_backfill_vendor_registers_when_absent():
    from src.app.services.supplier_catalog import _register_or_backfill_vendor
    seen = {}

    def lookup(*, tenant_id, domain):
        return None  # absent

    def register(**k):
        seen["reg"] = k
        return {"ok": True}

    def backfill(**k):
        seen["bf"] = k
        return True
    assert _register_or_backfill_vendor(lookup, register, backfill,
                                        tenant_id="default", name="X", domain="d.example",
                                        email="e@d.example") is True
    assert seen.get("reg", {}).get("contact_email") == "e@d.example"
    assert "bf" not in seen


def test_register_or_backfill_vendor_noop_when_complete():
    from src.app.services.supplier_catalog import _register_or_backfill_vendor
    def lookup(*, tenant_id, domain):
        return {"contact_email": "already@d.example"}
    def register(**k):
        raise AssertionError("must not register a duplicate")
    def backfill(**k):
        raise AssertionError("must not overwrite an existing contact")
    assert _register_or_backfill_vendor(lookup, register, backfill,
                                        tenant_id="default", name="X", domain="d.example",
                                        email="e@d.example") is False


def test_seed_demo_supplier_history_records_prior_dealings(tmp_path):
    # the demo-data fix: seed prior-dealings history so the draft evidence shows "N observations, last
    # invoice $X" instead of an empty supplier history. Idempotent on re-run.
    # Isolate on a FRESH engine: this test uses the AMBIENT global engine (no db arg), so a prior test
    # that swapped the engine / seeded supplier history would otherwise skew it (order-dependent flake).
    # record_email_event + the history read both CREATE-IF-NOT-EXISTS their tables, so a fresh sqlite works.
    from sqlalchemy import create_engine
    from src.app.models import db as dbmod
    from src.app.services.supplier_catalog import seed_demo_supplier_history
    from src.app.services.supplier_inbox_reader import recent_supplier_context
    prev = dbmod.get_engine()
    dbmod.set_engine(create_engine(f"sqlite+pysqlite:///{tmp_path / 'supplier_hist.sqlite'}", future=True))
    try:
        n = seed_demo_supplier_history()
        assert n >= 1
        ctx = recent_supplier_context(domain="approved-supplier.example", tenant_id="default")
        assert ctx is not None and ctx.observations >= 1
        assert ctx.last_invoice_cents is not None  # a "last quote" proxy lands on the draft evidence
        assert seed_demo_supplier_history() == 0  # idempotent on the isolated engine
    finally:
        dbmod.set_engine(prev)


def test_default_draft_path_resolves_seeded_supplier(tmp_path):
    """Integration: build_draft's DEFAULT path (no injected rank/allowlist fns) resolves the winning
    approved supplier — the live happy-path is unblocked. Isolated on a FRESH engine (the resolvers open
    their own db_session, so the ambient/polluted global engine would otherwise make this order-dependent)."""
    from sqlalchemy import create_engine
    from src.app.models import db as dbmod
    from src.app.models.db import db_session
    from src.app.services.fulfillment.draft import build_draft
    prev = dbmod.get_engine()
    dbmod.set_engine(create_engine(f"sqlite+pysqlite:///{tmp_path / 'sc_draft.sqlite'}", future=True))
    try:
        with db_session() as db:
            seed_demo(db, skus=["LAP-021"])
        with db_session() as db:
            draft = build_draft(db, item_ref="LAP-021", quantity=6, case_ref="FC-IT-1", estimated_value_cents=669000)
        assert draft is not None, "default draft path still resolves NO supplier — seed/enrichment broken"
        assert draft.recipient_domain == "approved-supplier.example"  # base SUP-7 wins on the clean engine
        assert draft.content_hash and "purchase order" in draft.body.lower()
        assert any("allowlist" in r for r in draft.rationale)
    finally:
        dbmod.set_engine(prev)
