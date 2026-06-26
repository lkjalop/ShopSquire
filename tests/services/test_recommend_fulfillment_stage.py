"""Step 6b — the extracted fulfilment stage: availability preserved + flag-gated case creation.

Default behaviour is unchanged (availability set, NO case). With the flag, a real bulk shortfall opens a
durable case advanced to GATE 1 (AWAITING_BUYER_COMMITMENT) and exposes a buyer-safe summary.
"""
from __future__ import annotations

import pytest

from src.app.services import recommend_fulfillment_stage as stage


@pytest.fixture(autouse=True)
def _stub_availability(monkeypatch):
    # deterministic availability so the stage logic is tested without the inventory DB
    monkeypatch.setattr("src.app.services.availability_agent.assess_availability",
                        lambda skus, qty, horizon, draft_reorder=False: {
                            "applicable": True, "sku": skus[0], "requested_qty": qty,
                            "in_stock": 4, "shortfall": max(0, qty - 4)})
    monkeypatch.setattr("src.app.services.availability_agent.availability_summary_line",
                        lambda avail: f"{avail['in_stock']} of {avail['requested_qty']} now")


def _run(flags, qty=10, results=None):
    payload = {}
    line = stage.run_fulfillment_stage(
        results=results if results is not None else [{"sku": "SKU-1"}],
        constraints={"order_quantity": qty}, payload=payload, uid="u1", trace_id="T1", flags=flags)
    return payload, line


def test_availability_preserved_default_no_case():
    payload, line = _run(flags={})
    assert payload["availability"]["shortfall"] == 6 and line == "4 of 10 now"
    assert "fulfillment_case" not in payload  # default: no case (parity)


def test_no_order_quantity_returns_empty():
    payload = {}
    assert stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}], constraints={}, payload=payload, flags={}) == ""
    assert "availability" not in payload


def test_flag_on_bulk_shortfall_opens_case_at_gate1():
    payload, _line = _run(flags={"FULFILLMENT_CASES_ENABLED": True}, qty=10)
    fc = payload.get("fulfillment_case")
    assert fc and fc["status"] == "awaiting_buyer_commitment" and fc["shortfall"] == 6
    # the durable case really exists and waits at GATE 1
    from src.app.models.db import db_session
    from src.app.services.fulfillment import workflow as fwf
    from src.app.services.fulfillment.domain import FulfillmentState as S
    with db_session() as db:
        assert fwf.current_state(db, fc["case_id"]) == S.AWAITING_BUYER_COMMITMENT
    # buyer-safe summary only — no supplier-private data leaked into the recommend payload
    assert set(fc.keys()) <= {"case_id", "status", "item_ref", "shortfall"}


def test_flag_on_but_no_shortfall_opens_no_case():
    payload, _ = _run(flags={"FULFILLMENT_CASES_ENABLED": True}, qty=4)  # 4 requested, 4 in stock → no shortfall
    assert "fulfillment_case" not in payload


def test_flag_on_below_threshold_opens_no_case():
    payload, _ = _run(flags={"FULFILLMENT_CASES_ENABLED": True, "FULFILLMENT_BULK_THRESHOLD": 50}, qty=10)
    assert "fulfillment_case" not in payload  # 10 < 50 threshold


# ── single-item out-of-stock ("do you have X?" → "no, we can source it") ──────
def test_single_item_oos_opens_case(monkeypatch):
    monkeypatch.setattr("src.app.services.availability_agent.assess_availability",
                        lambda skus, qty, horizon, draft_reorder=False: {
                            "applicable": True, "sku": skus[0], "requested_qty": qty,
                            "in_stock": 0, "shortfall": qty})  # fully out of stock
    payload = {}
    stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}], constraints={"availability_intent": True},
                                payload=payload, uid="u1", trace_id="T1",
                                flags={"FULFILLMENT_CASES_ENABLED": True, "FULFILLMENT_SINGLE_ITEM_OOS": True})
    fc = payload.get("fulfillment_case")
    assert fc and fc["status"] == "awaiting_buyer_commitment" and fc["shortfall"] == 1


def test_single_item_oos_disabled_by_default():
    # availability intent present, but the single-item flag is OFF → no availability, no case (parity)
    payload = {}
    line = stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}], constraints={"availability_intent": True},
                                       payload=payload, flags={"FULFILLMENT_CASES_ENABLED": True})
    assert line == "" and "availability" not in payload and "fulfillment_case" not in payload


def test_single_item_in_stock_opens_no_case(monkeypatch):
    monkeypatch.setattr("src.app.services.availability_agent.assess_availability",
                        lambda skus, qty, horizon, draft_reorder=False: {
                            "applicable": True, "sku": skus[0], "requested_qty": qty,
                            "in_stock": 3, "shortfall": 0})  # we have it
    payload = {}
    stage.run_fulfillment_stage(results=[{"sku": "SKU-1"}], constraints={"availability_intent": True},
                                payload=payload,
                                flags={"FULFILLMENT_CASES_ENABLED": True, "FULFILLMENT_SINGLE_ITEM_OOS": True})
    assert "fulfillment_case" not in payload  # in stock → no procurement
