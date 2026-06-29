"""Deal economics — operator-only margin/discount-headroom/profit math.

Proves the core calc (margin, the largest buyer discount that still clears the floor, profit after that
discount) and that from_case derives the inputs off a real case (wholesale from the validated quote,
retail from the selected option) — never inventing numbers when an input is absent.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import economics as E
from src.app.services.fulfillment import options as O
from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.domain import Actor, ActorType as A, FulfillmentState as S


# ── pure calc ────────────────────────────────────────────────────────────────
def test_margin_and_discount_headroom():
    # supplier charges 900.00, we list at 1200.00, qty 6, floor 10%
    e = E.compute(supplier_unit_cost_cents=90000, retail_unit_cents=120000, quantity=6, floor_margin_pct=0.10)
    assert e.supplier_cost_cents == 540000 and e.retail_cents == 720000
    assert e.gross_profit_cents == 180000 and e.margin_pct == 0.25 and e.clears_floor
    # min retail to keep 10% margin = 540000 / 0.9 = 600000 → headroom = 720000 − 600000 = 120000
    assert e.max_buyer_discount_cents == 120000
    # profit after handing the buyer the full headroom = floor margin on the floor retail = 60000
    assert e.profit_after_max_discount_cents == 60000


def test_thin_deal_below_floor_offers_no_discount():
    # list margin is only ~4.8% (< 10% floor) → no discount headroom, flagged
    e = E.compute(supplier_unit_cost_cents=100000, retail_unit_cents=105000, quantity=2, floor_margin_pct=0.10)
    assert e.clears_floor is False and e.max_buyer_discount_cents == 0


def test_compute_rejects_missing_or_nonpositive_inputs():
    assert E.compute(supplier_unit_cost_cents=None, retail_unit_cents=120000, quantity=1) is None
    assert E.compute(supplier_unit_cost_cents=90000, retail_unit_cents=0, quantity=1) is None
    assert E.compute(supplier_unit_cost_cents=90000, retail_unit_cents=120000, quantity=0) is None


# ── derivation from a case ───────────────────────────────────────────────────
@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def AG(): return Actor(A.AGENT, "Procurement_Agent")
def BU(): return Actor(A.BUYER, "u1")
def HU(): return Actor(A.HUMAN_OPERATOR, "owner-01")


def _to_selected(db, *, wholesale_cents=90000):
    """Walk to SELECTED. wholesale_cents=None omits the quoted wholesale (to test the catalog fallback)."""
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-26 09:00:00"); db.commit()
    vq = {"quoted_quantity": 6, "estimated_delivery_at": "2026-07-08", "confidence": 0.96}
    if wholesale_cents is not None:
        vq["unit_amount_cents"] = wholesale_cents
    seq = [
        ("availability_assessed", AG(), {"availability": {"requested_qty": 10, "in_stock": 4,
                                                          "shortfall": 6, "item_ref": "LAP-021"}}),
        ("request_buyer_commitment", AG(), None),
        ("buyer_committed", BU(), None),
        ("external_message_drafted", AG(),
         {"draft": {"content_hash": "H1", "commercial_scope": {"quantity": 6, "item_ref": "LAP-021"}}}),
        ("approval_requested", AG(), None),
        ("approval_granted", HU(), None),
        ("external_message_sent", HU(), None),
        ("external_message_received", Actor(A.EXTERNAL, "s"), None),
        ("supplier_quote_validated", HU(), {"validated_quote": vq}),
    ]
    ts = 0
    for event, actor, patch in seq:
        ts += 1
        assert wf.transition(db, case_id=cid, event=event, actor=actor, state_patch=patch,
                             now_iso=f"2026-06-26 09:0{ts}:00").ok, event
    # options priced at retail 1200.00/unit
    O.generate_and_record(db, case_id=cid, actor=AG(), unit_price_cents=120000,
                          local_delivery_at="2026-06-28", now_iso="2026-06-26 09:30:00")
    cur = wf.repository.current_version(db, cid)
    chosen = next(o for o in cur.state_json["options"] if o["option_type"] == O.OPTION_SHIP_TOGETHER)
    assert O.select_option(db, case_id=cid, actor=BU(), option_id=chosen["option_id"],
                           now_iso="2026-06-26 10:00:00").ok
    assert wf.current_state(db, cid) == S.SELECTED
    return cid


def test_from_case_derives_wholesale_and_retail(db):
    cid = _to_selected(db)
    econ = E.from_case(db, cid, floor_margin_pct=0.10)
    # supplier units = 6, wholesale 900.00, retail 1200.00 → margin 25%, headroom 1200.00 total
    assert econ and econ["quantity"] == 6
    assert econ["supplier_unit_cost_cents"] == 90000 and econ["retail_unit_cents"] == 120000
    assert econ["margin_pct"] == 0.25 and econ["max_buyer_discount_cents"] == 120000


def test_from_case_empty_before_quote_validated(db):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-26 09:00:00"); db.commit()
    assert E.from_case(db, cid) == {}  # no validated quote yet → no fabricated numbers


def test_from_case_retail_override(db):
    cid = _to_selected(db)
    econ = E.from_case(db, cid, retail_unit_cents=100000, floor_margin_pct=0.10)  # override retail to 1000.00
    assert econ["retail_unit_cents"] == 100000 and econ["supplier_unit_cost_cents"] == 90000


def test_from_case_uses_price_book_when_catalog_enabled(db, monkeypatch):
    from src.app.services import commerce_catalog as cc
    monkeypatch.setenv("COMMERCE_CATALOG_ENABLED", "1")
    cid = _to_selected(db)
    cc.upsert_price(db, sku="LAP-021", list_cents=130000, source="test"); db.commit()  # canonical 1300.00
    econ = E.from_case(db, cid, floor_margin_pct=0.10)
    assert econ["retail_unit_cents"] == 130000  # the price_book JOIN, not the 1200.00 option


def test_from_case_ignores_catalog_when_flag_off(db, monkeypatch):
    from src.app.services import commerce_catalog as cc
    # control the gate directly (it now reads env OR feature_flags.json — don't depend on ambient config)
    monkeypatch.setattr("src.app.services.commerce_catalog.catalog_enabled", lambda: False)
    cid = _to_selected(db)
    cc.upsert_price(db, sku="LAP-021", list_cents=130000, source="test"); db.commit()  # present but ignored
    econ = E.from_case(db, cid)
    assert econ["retail_unit_cents"] == 120000  # option-derived (flag off → no catalog read)


def test_from_case_wholesale_fallback_from_supplier_catalog(db, monkeypatch):
    # no live quote wholesale → fall back to the cheapest approved supplier's cost (catalog flag on)
    from src.app.services import commerce_catalog as cc
    from src.app.services.supplier_catalog import seed_demo as seed_suppliers
    monkeypatch.setenv("COMMERCE_CATALOG_ENABLED", "1")
    cid = _to_selected(db, wholesale_cents=None)
    seed_suppliers(db, skus=["LAP-021"])                              # cheapest = 1115.00 → 111500c
    cc.upsert_price(db, sku="LAP-021", list_cents=200000, source="t"); db.commit()  # retail 2000.00
    econ = E.from_case(db, cid, floor_margin_pct=0.10)
    assert econ["supplier_unit_cost_cents"] == 111500  # from supplier catalog, not a quote
    assert econ["retail_unit_cents"] == 200000
