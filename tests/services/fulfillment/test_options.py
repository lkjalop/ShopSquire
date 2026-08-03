"""Step 5 — the fulfilment options planner + buyer selection.

Options are ranked (complete + deadline-met + fewest deliveries + same product), each carries explicit
tradeoffs and which hard constraints it satisfies; a budget/deadline violation is SHOWN-but-flagged,
never silently chosen; and the buyer can only select an option that was offered.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import options as O
from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.domain import Actor, ActorType as A, FulfillmentState as S


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


# ── planner ──────────────────────────────────────────────────────────────────
def test_three_core_options_when_local_supplier_and_substitute(db):
    opts = O.plan_options(requested_qty=10, local_qty=4, confirmed_external_qty=6,
                          external_delivery_at="2026-07-08", local_delivery_at="2026-06-28",
                          substitute={"item_ref": "ALT-1", "local_qty": 10, "delivery_at": "2026-07-01",
                                      "tradeoff": "mixed fleet, slightly higher cost"})
    types = {o.option_type for o in opts}
    assert {O.OPTION_SHIP_TOGETHER, O.OPTION_SPLIT, O.OPTION_SUBSTITUTE_SHORTFALL} <= types
    assert all(o.tradeoffs for o in opts)  # every option states its tradeoffs


def test_ranking_prefers_complete_and_deadline_met(db):
    opts = O.plan_options(requested_qty=10, local_qty=4, confirmed_external_qty=6,
                          external_delivery_at="2026-07-08", deadline="2026-07-10",
                          substitute={"item_ref": "ALT-1", "local_qty": 10, "delivery_at": "2026-07-01"})
    # the top option is complete + deadline-met
    top = opts[0]
    assert top.constraints_satisfied["complete"] and top.constraints_satisfied["deadline_met"]


def test_deadline_miss_is_flagged_not_dropped(db):
    opts = O.plan_options(requested_qty=10, local_qty=4, confirmed_external_qty=6,
                          external_delivery_at="2026-08-30", deadline="2026-07-10")  # supplier too late
    together = next(o for o in opts if o.option_type == O.OPTION_SHIP_TOGETHER)
    assert together.constraints_satisfied["deadline_met"] is False  # shown but flagged


def test_missing_eta_or_deadline_is_unknown_not_optimistically_met(db):
    missing_eta = O.plan_options(
        requested_qty=10, local_qty=4, confirmed_external_qty=6,
        external_delivery_at=None, deadline="2026-08-14T17:00:00+10:00",
        unit_price_cents=10000,
    )
    together = next(o for o in missing_eta if o.option_type == O.OPTION_SHIP_TOGETHER)
    assert together.constraints_satisfied["deadline_met"] is None

    missing_deadline = O.plan_options(
        requested_qty=10, local_qty=4, confirmed_external_qty=6,
        external_delivery_at="2026-08-14T12:00:00+10:00", deadline=None,
        unit_price_cents=10000,
    )
    together = next(o for o in missing_deadline if o.option_type == O.OPTION_SHIP_TOGETHER)
    assert together.constraints_satisfied["deadline_met"] is None


def test_invalid_deadline_is_unknown(db):
    options = O.plan_options(
        requested_qty=10, local_qty=4, confirmed_external_qty=6,
        external_delivery_at="2026-08-14T12:00:00+10:00", deadline="not-a-date",
        unit_price_cents=10000,
    )
    together = next(o for o in options if o.option_type == O.OPTION_SHIP_TOGETHER)
    assert together.constraints_satisfied["deadline_met"] is None


def test_budget_violation_is_flagged(db):
    opts = O.plan_options(requested_qty=10, local_qty=4, confirmed_external_qty=6,
                          external_delivery_at="2026-07-08", unit_price_cents=150000, budget_per_unit_cents=149900)
    together = next(o for o in opts if o.option_type == O.OPTION_SHIP_TOGETHER)
    assert together.constraints_satisfied["within_budget"] is False


def test_reduce_option_when_shortfall_and_no_supplier(db):
    opts = O.plan_options(requested_qty=10, local_qty=4, confirmed_external_qty=0)
    assert any(o.option_type == O.OPTION_REDUCE and o.total_units == 4 for o in opts)


# ── wiring through the workflow ──────────────────────────────────────────────
def _to_validated(db):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-26 09:00:00"); db.commit()
    seq = [
        ("availability_assessed", AG(), {"availability": {"requested_qty": 10, "in_stock": 4, "shortfall": 6}}),
        ("request_buyer_commitment", AG(), None),
        ("buyer_committed", BU(), None),
        ("external_message_drafted", AG(), {"draft": {"content_hash": "H1", "commercial_scope": {"quantity": 6}}}),
        ("approval_requested", AG(), None),
        ("approval_granted", HU(), None),
        ("external_message_sent", HU(), None),
        ("external_message_received", Actor(A.EXTERNAL, "s"), None),
        ("supplier_quote_validated", HU(),
         {"validated_quote": {"quoted_quantity": 6, "estimated_delivery_at": "2026-07-08", "confidence": 0.96}}),
    ]
    ts = 0
    for event, actor, patch in seq:
        ts += 1
        assert wf.transition(db, case_id=cid, event=event, actor=actor, state_patch=patch,
                             now_iso=f"2026-06-26 09:0{ts}:00").ok, event
    assert wf.current_state(db, cid) == S.QUOTE_VALIDATED
    return cid


def test_generate_options_advances_and_persists(db):
    cid = _to_validated(db)
    res, opts = O.generate_and_record(db, case_id=cid, actor=AG(), local_delivery_at="2026-06-28",
                                      now_iso="2026-06-26 09:30:00")
    assert res.ok and wf.current_state(db, cid) == S.OPTIONS_READY and len(opts) >= 1
    cur = wf.repository.current_version(db, cid)
    assert cur.state_json["options"][0]["option_id"]


def test_generate_options_materializes_full_critical_path_for_every_live_option(db):
    cid = _to_validated(db)
    response = {
        "calendar_state": "open", "sla_clock": "running",
        "quote_due_at": "2026-06-26T12:00:00+00:00", "calendar_version": "cal-v1",
    }
    stages = {
        "operator_authorization": (60, 120), "allocation_confirmation": (60, 120),
        "dispatch_preparation": (3600, 7200), "transit": (3600, 7200),
        "inspection_or_cross_dock": (0, 60), "final_mile": (3600, 7200),
    }
    result, _ = O.generate_and_record(
        db, case_id=cid, actor=AG(), deadline="2026-07-10T17:00:00+00:00",
        local_delivery_at="2026-06-28T12:00:00+00:00",
        response_expectation=response, stage_duration_seconds=stages,
        carrier_cutoff_at="2026-06-27T17:00:00+00:00",
        dependency_versions={"atp": "snapshot-9"}, now_iso="2026-06-26T09:30:00+00:00",
    )
    assert result.ok
    current = wf.repository.current_version(db, cid)
    for option in current.state_json["options"]:
        promise = option["promise_calculation"]
        assert promise["calculation_version"].startswith("promise-critical-path-v1:")
        assert promise["response_expectation"]["calendar_version"] == "cal-v1"
        assert promise["dependency_versions"]["atp"] == "snapshot-9"


def test_buyer_selects_offered_option(db):
    cid = _to_validated(db)
    O.generate_and_record(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:30:00")
    cur = wf.repository.current_version(db, cid)
    chosen = cur.state_json["options"][0]["option_id"]
    res = O.select_option(db, case_id=cid, actor=BU(), option_id=chosen, now_iso="2026-06-26 10:00:00")
    assert res.ok and wf.current_state(db, cid) == S.SELECTED
    assert wf.repository.current_version(db, cid).state_json["selection"]["option_id"] == chosen


def test_buyer_cannot_select_unoffered_option(db):
    cid = _to_validated(db)
    O.generate_and_record(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:30:00")
    res = O.select_option(db, case_id=cid, actor=BU(), option_id="opt-made-up", now_iso="2026-06-26 10:00:00")
    assert res.ok is False and res.reason == "unknown_option"
    assert wf.current_state(db, cid) == S.OPTIONS_READY  # unchanged
