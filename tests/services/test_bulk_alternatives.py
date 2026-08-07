"""Bulk alternatives assembler (agnostic, pure): ordered buyer choices — partial now, transfer from the
network, substitutes, source-the-shortfall, reduce — built from gathered facts. Empty when fulfillable."""
from __future__ import annotations

from src.app.services.bulk_alternatives import (
    OPT_IN_STOCK, OPT_LATER_DELIVERY, OPT_REDUCE, OPT_SOURCE_SHORTFALL,
    OPT_SPLIT_DELIVERY, OPT_SUBSTITUTE, OPT_TRANSFER, augment_deadline_alternatives,
    build_alternatives,
)


def _types(opts):
    return [o["type"] for o in opts]


def test_empty_when_fully_fulfillable_at_preferred():
    out = build_alternatives(sku="X", requested_qty=10, in_stock=10, shortfall=0,
                             network={"fully_in_preferred": True})
    assert out == []


def test_transfer_when_network_can_cover_the_gap():
    net = {"transfer_plan": [{"from_location": "melbourne", "qty": 5}],
           "fully_in_preferred": False, "fillable_from_network": True}
    out = build_alternatives(sku="X", requested_qty=10, in_stock=5, shortfall=0, network=net)
    t = _types(out)
    assert OPT_IN_STOCK in t and OPT_TRANSFER in t and OPT_REDUCE in t
    transfer = next(o for o in out if o["type"] == OPT_TRANSFER)
    assert transfer["covers_full_order"] is True and transfer["transfer_plan"] == net["transfer_plan"]
    assert OPT_SOURCE_SHORTFALL not in t  # network covers it → no supplier needed


def test_source_shortfall_and_substitutes_when_network_short():
    subs = [{"sku": "ALT-A", "name": "Alt A", "tradeoff": "$50 more; 2/2 key specs", "price_cents": 155000,
             "spec_match": 2, "spec_total": 2}]
    out = build_alternatives(sku="X", requested_qty=30, in_stock=5, shortfall=13,
                             network={"transfer_plan": [{"from_location": "wh", "qty": 12}],
                                      "fillable_from_network": False},
                             substitutes=subs, horizon_days=10)
    t = _types(out)
    assert OPT_SOURCE_SHORTFALL in t and OPT_SUBSTITUTE in t
    src = next(o for o in out if o["type"] == OPT_SOURCE_SHORTFALL)
    assert src["shortfall"] == 13 and "10-day" in src["detail"]
    sub = next(o for o in out if o["type"] == OPT_SUBSTITUTE)
    assert sub["sku"] == "ALT-A" and sub["option_id"] == "substitute:ALT-A"


def test_substitutes_capped():
    subs = [{"sku": f"A{i}", "name": f"A{i}", "tradeoff": "x"} for i in range(6)]
    out = build_alternatives(sku="X", requested_qty=20, in_stock=0, shortfall=20,
                             substitutes=subs, max_substitutes=2)
    assert sum(1 for o in out if o["type"] == OPT_SUBSTITUTE) == 2


def test_no_requested_qty_returns_empty():
    assert build_alternatives(sku="X", requested_qty=0, in_stock=0, shortfall=0) == []


def test_deadline_alternatives_add_split_and_known_later_date_without_claiming_supplier_atp():
    existing = [{"option_id": OPT_SOURCE_SHORTFALL, "type": OPT_SOURCE_SHORTFALL}]
    result = augment_deadline_alternatives(
        existing,
        promise={
            "feasibility": "missed",
            "requested_quantity": 30,
            "quantity_confirmed_by_deadline": 7,
            "remaining_quantity": 23,
            "requested_arrival_at": "2026-08-10T00:00:00+00:00",
            "supply_lines": [
                {"source_ref": "SYD", "quantity": 7, "status": "confirmed",
                 "arrival_max": "2026-08-09T00:00:00+00:00"},
                {"source_ref": "MEL", "quantity": 23, "status": "confirmed",
                 "arrival_max": "2026-08-13T00:00:00+00:00"},
            ],
        },
    )
    types = _types(result)
    assert OPT_SPLIT_DELIVERY in types
    assert OPT_LATER_DELIVERY in types
    later = next(item for item in result if item["type"] == OPT_LATER_DELIVERY)
    assert later["arrival_status"] == "confirmed"
    assert later["external_action"] == "none"


def test_unknown_arrival_never_becomes_later_delivery_option():
    result = augment_deadline_alternatives(
        [],
        promise={
            "feasibility": "unknown", "requested_quantity": 30,
            "quantity_confirmed_by_deadline": 0, "remaining_quantity": 30,
            "supply_lines": [{"source_ref": "supplier_enquiry", "quantity": 30,
                              "status": "unconfirmed", "arrival_max": None}],
        },
    )
    assert OPT_LATER_DELIVERY not in _types(result)
