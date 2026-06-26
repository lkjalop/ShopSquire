"""Buyer procurement TRUTH — the canonical catalog drives the shortfall that opens a fulfilment case.

The credibility fix (P0): a bulk order for more units than the CANONICAL catalog holds must report a
real shortfall and open the procurement case (so the buyer sees the FulfilmentOptions panel); a bulk
order within canonical stock must NOT. This exercises the REAL path
recommend_fulfillment_stage → availability_agent → inventory_source (adapter) → commerce_catalog,
with no availability stub.
"""
from __future__ import annotations

import pytest

from src.app.models.db import db_session
from src.app.services import commerce_catalog as cc
from src.app.services import recommend_fulfillment_stage as stage


@pytest.fixture(autouse=True)
def _fast_reorder(monkeypatch):
    # keep the bulk path off the real demand forecaster — we're testing the shortfall→case trigger
    monkeypatch.setattr("src.app.services.availability_agent._default_reorder_fn",
                        lambda sku, current_stock, reorder_point: {"status": "awaiting_human_approval"})


def _seed_stock(sku: str, on_hand: int) -> None:
    with db_session() as db:
        cc.upsert_inventory(db, sku=sku, on_hand=on_hand, source="test")
        db.commit()


def _run(qty: int, flags: dict) -> dict:
    payload: dict = {}
    stage.run_fulfillment_stage(results=[{"sku": "LAP-021"}], constraints={"order_quantity": qty},
                                payload=payload, uid="u1", trace_id="T-PT-1", flags=flags)
    return payload


def test_canonical_short_stock_opens_case(monkeypatch):
    monkeypatch.setenv("COMMERCE_CATALOG_ENABLED", "1")
    _seed_stock("LAP-021", 4)                       # catalog has only 4
    payload = _run(10, {"FULFILLMENT_CASES_ENABLED": True})
    assert payload["availability"]["in_stock"] == 4 and payload["availability"]["shortfall"] == 6
    fc = payload.get("fulfillment_case")
    assert fc and fc["status"] == "awaiting_buyer_commitment" and fc["shortfall"] == 6


def test_canonical_sufficient_stock_opens_no_case(monkeypatch):
    monkeypatch.setenv("COMMERCE_CATALOG_ENABLED", "1")
    _seed_stock("LAP-021", 50)                      # catalog has plenty
    payload = _run(10, {"FULFILLMENT_CASES_ENABLED": True})
    assert payload["availability"]["in_stock"] == 50 and payload["availability"]["shortfall"] == 0
    assert "fulfillment_case" not in payload        # no shortfall → no case


def test_flag_off_does_not_consult_canonical(monkeypatch):
    monkeypatch.delenv("COMMERCE_CATALOG_ENABLED", raising=False)
    _seed_stock("LAP-021", 4)                       # present, but flag off → legacy source only
    payload = _run(10, {"FULFILLMENT_CASES_ENABLED": True})
    # legacy batch_stock_levels has no row for LAP-021 → 0 in stock → shortfall is the full order
    assert payload["availability"]["in_stock"] == 0 and payload["availability"]["shortfall"] == 10
