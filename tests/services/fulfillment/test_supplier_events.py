"""Phase 7 — supplier out-of-band write-bus: record a supplier contact + fan it out to open cases."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment.cart_commitment import materialize_cases_for_order
from src.app.services.fulfillment.supplier_events import (
    record_supplier_event, recent_supplier_oob_events)
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
    db.execute(text("CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, name TEXT, specs TEXT, active INTEGER DEFAULT 1)"))
    db.execute(text("INSERT INTO products (sku, name, specs, active) VALUES (:s, :n, '{}', 1)"), {"s": sku, "n": name})


def test_record_supplier_event_fans_out_to_open_cases_for_that_domain(db):
    # a case sourced from creatorfleet.example exists; an out-of-band "lead time slipped" event must attach
    # to THAT case (and only it), and be queryable per domain.
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    gam = materialize_cases_for_order(db, order_id="O-1", uid="u1",
                                      lines=[{"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0}])
    mon = materialize_cases_for_order(db, order_id="O-2", uid="u1",
                                      lines=[{"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0}])
    gam_case = gam["cases"][0]["case_id"]
    mon_case = mon["cases"][0]["case_id"]

    out = record_supplier_event(db, supplier_domain="creatorfleet.example", kind="lead_time_change",
                                note="Supplier phoned: lead time slipped to 3 weeks.")
    assert out["event_id"] and out["kind"] == "lead_time_change"
    assert gam_case in out["affected_cases"]            # the CreatorFleet case is notified
    assert mon_case not in out["affected_cases"]        # the PeriLink case is NOT

    events = recent_supplier_oob_events(db, supplier_domain="creatorfleet.example")
    assert events and events[0]["note"].startswith("Supplier phoned")


def test_record_supplier_event_unknown_kind_falls_back_to_general(db):
    out = record_supplier_event(db, supplier_domain="creatorfleet.example", kind="bogus", note="hi")
    assert out["kind"] == "general"


def test_record_supplier_event_blank_inputs_are_safe_noop(db):
    assert record_supplier_event(db, supplier_domain="", note="x")["event_id"] is None
    assert record_supplier_event(db, supplier_domain="d.example", note="")["event_id"] is None
