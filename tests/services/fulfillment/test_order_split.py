from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.order_split import (
    create_grouped_cases, parse_order_lines, plan_order_split, resolve_line_skus,
)
from src.app.services.supplier_catalog import ensure_supplier_coverage


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _seed_product(db, sku: str, name: str, specs: dict | None = None) -> None:
    db.execute(text(
        "CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, name TEXT, specs TEXT, active INTEGER DEFAULT 1)"
    ))
    db.execute(text(
        "INSERT INTO products (sku, name, specs, active) VALUES (:s, :n, :p, 1)"
    ), {"s": sku, "n": name, "p": json.dumps(specs or {})})


def test_plan_order_split_routes_mixed_lines_to_distinct_suppliers(db):
    _seed_product(db, "GAM-0002", "HP Victus 16 Gaming Laptop with RTX graphics")
    _seed_product(db, "MON-1", "LG UltraGear 34 inch monitor")
    _seed_product(db, "NET-1", "TP-Link Wi-Fi 6 router")
    ensure_supplier_coverage(db)

    plan = plan_order_split(db, lines=[
        {"item_ref": "GAM-0002", "requested_qty": 20, "in_stock": 13},
        {"item_ref": "MON-1", "requested_qty": 30, "in_stock": 5},
        {"item_ref": "NET-1", "requested_qty": 5, "in_stock": 5},
    ])

    assert plan["line_count"] == 3
    assert plan["sourcing_line_count"] == 2
    assert plan["group_count"] == 2
    by_sku = {line["item_ref"]: line for line in plan["lines"]}
    assert by_sku["GAM-0002"]["supplier_ref"] == "SUP-CREATOR"
    assert by_sku["GAM-0002"]["recipient_domain"] == "creatorfleet.example"
    assert by_sku["GAM-0002"]["below_moq"] is True
    assert "25+ units" in by_sku["GAM-0002"]["price_break_advisory"]
    assert by_sku["MON-1"]["supplier_ref"] == "SUP-PERIPH"
    assert by_sku["MON-1"]["recipient_domain"] == "perilink-accessories.example"
    assert by_sku["NET-1"]["status"] == "fillable_from_stock"


def test_plan_order_split_marks_missing_supplier_without_contacting_external_party(db):
    plan = plan_order_split(db, lines=[
        {"item_ref": "UNKNOWN-SKU", "requested_qty": 12, "in_stock": 0},
    ])

    assert plan["line_count"] == 1
    assert plan["sourcing_line_count"] == 0
    assert plan["group_count"] == 0
    assert plan["lines"][0]["status"] == "no_approved_supplier"
    assert plan["lines"][0]["supplier_candidates"] == []


# ── multi-line: parse → resolve → create one case per supplier group ──
def test_parse_order_lines_extracts_count_and_noun():
    out = parse_order_lines("i need 15 laptops + 10 monitors and 5 headsets in 10 days, budget about 1900 each")
    got = {l["phrase"]: l["quantity"] for l in out}
    assert got.get("laptops") == 15 and got.get("monitors") == 10 and got.get("headsets") == 5
    assert "days" not in got and "each" not in got           # time/currency never a line
    assert parse_order_lines("just one laptop please") == []  # no multi-quantity line


def test_resolve_line_skus_maps_phrase_to_catalog_sku(db):
    _seed_product(db, "LAP-9", "Dell Latitude business laptop")
    _seed_product(db, "MON-1", "LG UltraGear 34 inch monitor")
    db.commit()
    resolved = resolve_line_skus(db, parse_order_lines("15 laptops + 10 monitors"))
    by = {r["item_ref"]: r for r in resolved}
    assert by["LAP-9"]["requested_qty"] == 15 and by["MON-1"]["requested_qty"] == 10


def test_create_grouped_cases_makes_one_case_per_supplier_group(db):
    _seed_product(db, "GAM-0002", "HP Victus Gaming Laptop RTX")
    _seed_product(db, "MON-1", "LG monitor")
    _seed_product(db, "HDS-1", "Sony headset")
    ensure_supplier_coverage(db)
    plan = plan_order_split(db, lines=[
        {"item_ref": "GAM-0002", "requested_qty": 7, "in_stock": 0},   # → SUP-CREATOR
        {"item_ref": "MON-1", "requested_qty": 10, "in_stock": 0},      # → SUP-PERIPH
        {"item_ref": "HDS-1", "requested_qty": 5, "in_stock": 0},       # → SUP-PERIPH (grouped)
    ])
    out = create_grouped_cases(db, plan=plan, uid="u1")
    assert out["case_count"] == 2                                       # CreatorFleet + PeriLink
    suppliers = {c["supplier_ref"]: c for c in out["cases"]}
    assert "SUP-CREATOR" in suppliers and "SUP-PERIPH" in suppliers
    peri = suppliers["SUP-PERIPH"]
    assert {l["item_ref"] for l in peri["lines"]} == {"MON-1", "HDS-1"}  # both peripherals in ONE case
    assert peri["total_quantity"] == 15
    # every case shares the order group and waits at GATE 1 (no supplier contacted)
    assert len({c["case_id"] for c in out["cases"]}) == 2
    for c in out["cases"]:
        cur = wf.repository.current_version(db, c["case_id"])
        assert cur.state == "AWAITING_BUYER_COMMITMENT"
        assert cur.state_json["order_group_id"] == out["order_group_id"]


def test_recommend_stage_routes_mixed_query_to_grouped_cases(monkeypatch):
    # the buyer-chat path: a mixed query → _maybe_multiline_order creates grouped cases + a buyer-safe summary
    from src.app.services import recommend_fulfillment_stage as stage
    monkeypatch.setattr(stage, "_maybe_multiline_order",
                        lambda *, query, uid, uid_hash, trace_id, payload: (
                            payload.__setitem__("order_group", {"case_count": 2, "lines": [1, 2]})
                            or "split into 2 sourcing requests"))
    payload = {}
    line = stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}],
                                       constraints={"order_quantity": 30}, payload=payload, uid="u1",
                                       query="15 laptops + 10 monitors", flags={"FULFILLMENT_CASES_ENABLED": True})
    assert "2 sourcing requests" in line                     # multi-line summary returned
    assert payload["order_group"]["case_count"] == 2
    assert "availability" not in payload                     # short-circuited the single-line path


# ── Phase 1 (fluid-procurement): FULFILLMENT_DEFER_TO_CART previews, never materializes a durable case ──
def test_defer_to_cart_uses_fluid_multiline_path_not_eager(monkeypatch):
    # with the defer flag ON, a mixed query takes the read-only FLUID path (preview), NOT the eager path
    # that creates durable cases — this is what kills the orphaned-case churn from browsing queries.
    from src.app.services import recommend_fulfillment_stage as stage
    called = {}
    monkeypatch.setattr(stage, "_fluid_multiline_intent",
                        lambda *, query, trace_id, payload: (called.__setitem__("fluid", True) or "preview only"))
    monkeypatch.setattr(stage, "_maybe_multiline_order",
                        lambda **k: (called.__setitem__("eager", True) or "EAGER"))
    payload = {}
    line = stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}], constraints={"order_quantity": 30},
                                       payload=payload, uid="u1", query="15 laptops + 10 monitors",
                                       flags={"FULFILLMENT_CASES_ENABLED": True, "FULFILLMENT_DEFER_TO_CART": True})
    assert called.get("fluid") is True and "eager" not in called
    assert line == "preview only"


def test_defer_to_cart_single_bulk_sets_fluid_intent_no_case():
    # a single bulk shortfall under defer mode → payload['sourcing_intent'] (preview), NO durable case opened
    # (the defer branch returns before any DB/workflow access — verifiable without a DB).
    from src.app.services import recommend_fulfillment_stage as stage
    payload = {}
    stage._maybe_open_case(payload=payload, avail={"sku": "GAM-1", "shortfall": 8, "in_stock": 2},
                           order_qty=10, uid="u1", uid_hash=None, trace_id=None,
                           flags={"FULFILLMENT_CASES_ENABLED": True}, defer=True)
    si = payload.get("sourcing_intent")
    assert si and si["mode"] == "deferred_to_cart"
    assert si["lines"][0] == {"item_ref": "GAM-1", "quantity": 10, "shortfall": 8}
    assert si["planned_case_count"] == 1
    assert "fulfillment_case" not in payload                  # NOTHING durable was created
