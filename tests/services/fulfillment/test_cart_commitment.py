"""Phase 2 — cart-commitment materialization: GATE 1 at the buyer's CONFIRM, idempotent on the order id."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import text

from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.cart_commitment import (
    materialize_cases_for_order, order_group_id_for, supersede_order)
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
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, name TEXT, specs TEXT, active INTEGER DEFAULT 1)"
    ))
    db.execute(text("INSERT INTO products (sku, name, specs, active) VALUES (:s, :n, :p, 1)"),
               {"s": sku, "n": name, "p": json.dumps({})})


def test_order_group_id_is_deterministic_from_order_id():
    assert order_group_id_for("ORD-1") == "order-ORD-1"
    assert order_group_id_for("  ORD-2  ") == "order-ORD-2"
    assert order_group_id_for("") is None


def test_materialize_creates_grouped_cases_then_is_idempotent(db):
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    lines = [{"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0},   # → SUP-CREATOR
             {"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0}]      # → SUP-PERIPH

    r1 = materialize_cases_for_order(db, order_id="ORD-1", lines=lines, uid="u1")
    assert r1["idempotent"] is False
    assert r1["case_count"] == 2
    assert r1["order_group_id"] == "order-ORD-1"
    # each materialized case waits at GATE 1, no supplier contacted
    for c in r1["cases"]:
        cur = wf.repository.current_version(db, c["case_id"])
        assert cur.state == "AWAITING_BUYER_COMMITMENT"
        assert cur.state_json["order_group_id"] == "order-ORD-1"

    # RE-CONFIRM the same order (double-submit) → SAME cases, NO duplicates (the "two POs" bug killed)
    r2 = materialize_cases_for_order(db, order_id="ORD-1", lines=lines, uid="u1")
    assert r2["idempotent"] is True
    assert r2["case_count"] == 2
    assert {c["case_id"] for c in r2["cases"]} == {c["case_id"] for c in r1["cases"]}


def test_reconfirm_with_changed_lines_is_amend_required_not_silent(db):
    # the mind-change-after-commit gap: same order_id, DIFFERENT lines → must NOT silently return the stale
    # cases and must NOT duplicate — it signals amend_required (supersession) so Phase 4 can act on it.
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    first = [{"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0}]
    r1 = materialize_cases_for_order(db, order_id="ORD-9", lines=first, uid="u1")
    assert r1["case_count"] == 1 and r1["idempotent"] is False and not r1.get("amend_required")

    # same order, now the buyer wants a DIFFERENT item/qty → amend_required, original cases untouched
    changed = [{"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0}]
    r2 = materialize_cases_for_order(db, order_id="ORD-9", lines=changed, uid="u1")
    assert r2["amend_required"] is True and r2["reason"] == "order_lines_changed"
    assert r2["idempotent"] is False
    assert {c["case_id"] for c in r2["cases"]} == {c["case_id"] for c in r1["cases"]}  # no new cases

    # an IDENTICAL re-submit (same lines) is still a clean idempotent no-op (double-submit guard intact)
    r3 = materialize_cases_for_order(db, order_id="ORD-9", lines=first, uid="u1")
    assert r3["idempotent"] is True and not r3.get("amend_required")


def test_supersede_order_retires_pre_send_cases_and_resources(db):
    # the FULL mind-change-after-commit action: supersede the old pre-send case(s) + materialize the new
    # lines (possibly a different supplier), and the probe then ignores the superseded case.
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    r1 = materialize_cases_for_order(db, order_id="ORD-S", uid="u1",
                                     lines=[{"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0}])
    old_case = r1["cases"][0]["case_id"]
    assert wf.repository.current_version(db, old_case).state == "AWAITING_BUYER_COMMITMENT"

    sup = supersede_order(db, order_id="ORD-S", uid="u1",
                          lines=[{"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0}])
    assert sup["status"] == "superseded"
    assert old_case in sup["superseded"]
    assert sup["created"]["case_count"] == 1
    new_case = sup["created"]["cases"][0]["case_id"]
    assert new_case != old_case
    assert wf.repository.current_version(db, old_case).state == "SUPERSEDED"          # old retired
    assert wf.repository.current_version(db, new_case).state == "AWAITING_BUYER_COMMITMENT"  # new active

    # re-confirming the NEW lines is now idempotent against the NEW case (superseded one is ignored)
    r2 = materialize_cases_for_order(db, order_id="ORD-S", uid="u1",
                                     lines=[{"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0}])
    assert r2["idempotent"] is True and {c["case_id"] for c in r2["cases"]} == {new_case}


def test_supersede_carries_requirements_forward_when_amend_omits_them(db):
    # the live bug: after amendment the RFQ lost the concrete deadline. supersede_order must inherit the
    # original requirements (deadline/use_case) when the amend confirm does not restate them.
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    materialize_cases_for_order(db, order_id="ORD-RF", uid="u1",
                                requirements={"needed_by": "2026-07-07", "use_case": "gaming"},
                                lines=[{"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0}])
    # amend WITHOUT restating requirements (the API path the live test exercised)
    sup = supersede_order(db, order_id="ORD-RF", uid="u1", requirements=None,
                          lines=[{"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0}])
    new_case = sup["created"]["cases"][0]["case_id"]
    sj = wf.repository.current_version(db, new_case).state_json
    assert sj.get("requirements", {}).get("needed_by") == "2026-07-07"   # inherited, not lost
    assert sj["requirements"]["use_case"] == "gaming"


def test_operator_supersede_then_late_reply_is_quarantined(db):
    # post-send supersession safety: an operator retires a case, and a LATE supplier reply to that
    # superseded RFQ is quarantined (superseded_rfq) rather than processed as a live quote.
    from src.app.services.fulfillment.cart_commitment import operator_supersede_case
    from src.app.services.fulfillment.external_comms import receive_reply
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    ensure_supplier_coverage(db)
    r1 = materialize_cases_for_order(db, order_id="OPS-1", uid="u1",
                                     lines=[{"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0}])
    cid = r1["cases"][0]["case_id"]

    out = operator_supersede_case(db, case_id=cid, reason="buyer_amended_order")
    assert out["ok"] is True
    assert wf.repository.current_version(db, cid).state == "SUPERSEDED"

    res = receive_reply(db, case_id=cid, raw_body="quote: 7 units, lead 5 days",
                        sender_domain="creatorfleet.example", trusted_fn=lambda d: True)
    assert res.ok is False and res.reason == "superseded_rfq"   # late quote for a retired RFQ → quarantined


def test_materialize_threads_requirements_onto_the_case(db):
    # Gap 3: the buyer's deadline/use_case must survive cart-confirmation and land on the case so the supplier
    # RFQ carries a CONCRETE deadline (not the vague placeholder that blocks autonomous send).
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    ensure_supplier_coverage(db)
    reqs = {"needed_by": "2026-07-07", "use_case": "gaming", "ship_to": "AU-metro"}
    r = materialize_cases_for_order(db, order_id="ORD-R", uid="u1", requirements=reqs,
                                    lines=[{"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0}])
    cid = r["cases"][0]["case_id"]
    sj = wf.repository.current_version(db, cid).state_json
    assert sj.get("requirements", {}).get("needed_by") == "2026-07-07"
    assert sj["requirements"]["use_case"] == "gaming"


def test_materialize_skips_fully_in_stock_lines(db):
    # a line we can fully fulfil from stock needs no sourcing → no case is created
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    r = materialize_cases_for_order(db, order_id="ORD-2", uid="u1",
                                    lines=[{"item_ref": "MON-1", "requested_qty": 5, "in_stock": 10}])
    assert r["case_count"] == 0 and r["idempotent"] is False


def test_materialize_honors_explicit_source_qty_even_when_stock_exists(db):
    # Explicit supplier sourcing from the buyer preview must not be recomputed away by current retail stock.
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    ensure_supplier_coverage(db)
    r = materialize_cases_for_order(db, order_id="ORD-SRC", uid="u1",
                                    lines=[{"item_ref": "GAM-0002", "requested_qty": 7,
                                            "in_stock": 10, "source_qty": 7}])
    assert r["case_count"] == 1 and r["idempotent"] is False
    cid = r["cases"][0]["case_id"]
    sj = wf.repository.current_version(db, cid).state_json
    assert sj["availability"]["requested_qty"] == 7
    assert sj["availability"]["shortfall"] == 7


def test_materialize_blank_order_id_is_a_safe_noop(db):
    _seed_product(db, "MON-1", "LG monitor")
    ensure_supplier_coverage(db)
    r = materialize_cases_for_order(db, order_id="", uid="u1",
                                    lines=[{"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0}])
    assert r["order_group_id"] is None and r["case_count"] == 0
