"""Multi-location availability + transfer feasibility (agnostic): per-location stock surfaced, the
preferred-location gap filled by a transfer plan from other locations before any supplier reorder, and
the true network shortfall (what no location can cover) reported. Vertical-blind (sku/location/qty)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.multi_location_availability import (
    assess_network_availability, network_availability, stock_by_location,
)


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    s.execute(text("CREATE TABLE inventory_level (tenant_id TEXT, sku TEXT, location_id TEXT, "
                   "on_hand INT, reserved INT, available INT)"))
    rows = [("default", "LAP-1", "sydney", 5), ("default", "LAP-1", "melbourne", 12),
            ("default", "LAP-1", "warehouse", 8), ("default", "LAP-2", "sydney", 0)]
    for t, sku, loc, avail in rows:
        s.execute(text("INSERT INTO inventory_level VALUES (:t,:k,:l,:a,0,:a)"),
                  {"t": t, "k": sku, "l": loc, "a": avail})
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_stock_by_location_breaks_down_per_location(db):
    out = stock_by_location(db, ["LAP-1", "LAP-2"])
    assert out["LAP-1"] == {"sydney": 5, "melbourne": 12, "warehouse": 8}
    assert "LAP-2" not in out  # zero-stock location omitted (not zeroed)


def test_network_fully_in_preferred():
    r = network_availability("X", 4, by_location={"sydney": 5, "melbourne": 12}, preferred_location="sydney")
    assert r["fully_in_preferred"] is True and r["transfer_plan"] == [] and r["shortfall"] == 0


def test_network_transfer_plan_fills_preferred_gap():
    # need 10 at sydney, only 5 there → transfer 5 from the largest other location (melbourne)
    r = network_availability("X", 10, by_location={"sydney": 5, "melbourne": 12, "warehouse": 8},
                             preferred_location="sydney")
    assert r["fully_in_preferred"] is False
    assert r["fillable_from_network"] is True and r["shortfall"] == 0
    assert r["transfer_plan"] == [{"from_location": "melbourne", "qty": 5}]


def test_network_transfer_spans_multiple_locations():
    # need 20 at sydney, 5 there, 8 + 8 elsewhere → transfer 8 + 7 (largest-first, deterministic)
    r = network_availability("X", 20, by_location={"sydney": 5, "a": 8, "b": 8},
                             preferred_location="sydney")
    assert r["transfer_plan"] == [{"from_location": "a", "qty": 8}, {"from_location": "b", "qty": 7}]
    assert r["shortfall"] == 0  # 5+8+8 = 21 >= 20


def test_network_shortfall_when_even_network_is_short():
    r = network_availability("X", 30, by_location={"sydney": 5, "melbourne": 12}, preferred_location="sydney")
    assert r["fillable_from_network"] is False
    assert r["shortfall"] == 13           # 30 - 17 → the bit a supplier reorder must cover
    assert r["total_in_network"] == 17


def test_assess_network_availability_end_to_end(db):
    r = assess_network_availability(db, ["LAP-1"], 10, preferred_location="sydney")
    assert r["applicable"] and r["total_in_network"] == 25 and r["shortfall"] == 0
    assert r["transfer_plan"] == [{"from_location": "melbourne", "qty": 5}]  # fill sydney's 5-unit gap


def test_assess_network_not_applicable_on_empty():
    assert assess_network_availability(None, [], 0) == {"applicable": False}
