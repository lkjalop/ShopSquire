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


def test_parse_order_lines_tolerates_adjectives_between_count_and_noun():
    # the live gap: "20 gaming laptops + 20 headsets" dropped headsets because the adjective broke the
    # count↔noun match → whole thing fell to the single-line path. Now both lines parse.
    got = {l["phrase"]: l["quantity"] for l in parse_order_lines("20 gaming laptops + 20 headsets")}
    assert got == {"laptops": 20, "headsets": 20}
    got2 = {l["phrase"]: l["quantity"] for l in parse_order_lines("10 wireless mechanical keyboards + 5 monitors")}
    assert got2.get("keyboards") == 10 and got2.get("monitors") == 5


def test_resolve_line_skus_maps_phrase_to_catalog_sku(db):
    _seed_product(db, "LAP-9", "Dell Latitude business laptop")
    _seed_product(db, "MON-1", "LG UltraGear 34 inch monitor")
    db.commit()
    resolved = resolve_line_skus(db, parse_order_lines("15 laptops + 10 monitors"))
    by = {r["item_ref"]: r for r in resolved}
    assert by["LAP-9"]["requested_qty"] == 15 and by["MON-1"]["requested_qty"] == 10


# ── Pass B: no line or quantity is ever silently dropped ──────────────────────
def test_collision_sums_quantities_no_qty_loss(db):
    """D1: two phrases that resolve to the SAME sku must SUM (buyer ordered 15, gets 15), never drop the 2nd."""
    from src.app.services.fulfillment.order_split import resolve_line_skus_detailed
    _seed_product(db, "LAP-1", "Acer laptop")  # the only laptop → both phrases resolve here
    db.commit()
    d = resolve_line_skus_detailed(db, parse_order_lines("10 gaming laptops + 5 work laptops"))
    assert len(d["resolved"]) == 1 and d["resolved"][0]["requested_qty"] == 15   # SUMMED, not 10
    assert d["unresolved"] == []


def test_unresolved_phrase_is_surfaced_not_dropped(db):
    """L5: a phrase that matches no product is surfaced in `unresolved`, never silently discarded."""
    from src.app.services.fulfillment.order_split import resolve_line_skus_detailed
    _seed_product(db, "LAP-9", "Dell laptop")
    db.commit()
    d = resolve_line_skus_detailed(db, parse_order_lines("15 laptops + 7 flux-capacitors"))
    assert [r["item_ref"] for r in d["resolved"]] == ["LAP-9"]
    assert len(d["unresolved"]) == 1 and d["unresolved"][0]["quantity"] == 7
    # nothing lost: every parsed unit is accounted for in resolved + unresolved
    parsed_units = sum(l["quantity"] for l in parse_order_lines("15 laptops + 7 flux-capacitors"))
    accounted = sum(r["requested_qty"] for r in d["resolved"]) + sum(u["quantity"] for u in d["unresolved"])
    assert accounted == parsed_units == 22


def test_partial_resolution_does_not_collapse_to_single_line(monkeypatch):
    """L6: a 2-phrase order where one phrase fails must still surface the resolved line + the unresolved one
    via the fluid preview — NOT collapse to the single-line path (which would lose the resolved line)."""
    import src.app.services.recommend_fulfillment_stage as stage
    from src.app.services.fulfillment import order_split as os_
    monkeypatch.setattr(os_, "resolve_line_skus_detailed",
                        lambda db, lines, **k: {"resolved": [{"item_ref": "LAP-9", "requested_qty": 15, "phrase": "laptops"}],
                                                "unresolved": [{"phrase": "widgets", "quantity": 5}]})
    monkeypatch.setattr(os_, "plan_order_split", lambda db, lines: {"group_count": 1})
    monkeypatch.setattr(os_, "emit_split_trace", lambda *a, **k: None)
    payload = {}
    line = stage._fluid_multiline_intent(query="15 laptops + 5 widgets", constraints={}, trace_id="T", payload=payload)
    si = payload["sourcing_intent"]
    assert [l["item_ref"] for l in si["lines"]] == ["LAP-9"]            # the resolved line survived
    assert si["unresolved_phrases"] == [{"phrase": "widgets", "quantity": 5}]  # the unmatched one is surfaced
    assert "couldn't match" in line


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
                        lambda *, query, constraints, trace_id, payload, pr_id=None: (called.__setitem__("fluid", True) or "preview only"))
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
