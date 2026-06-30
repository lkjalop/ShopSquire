"""Gate-3 change-order / cancellation — the irreversibility ladder.

Proves: a committed order is NOT superseded; the AGENT may PROPOSE a change but only a HUMAN may CANCEL
(governance); the economics are surfaced; the original order is preserved; CANCELLED is terminal.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import change_order as CO
from src.app.services.fulfillment import options as O
from src.app.services.fulfillment import purchase_order as PO
from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment import domain as d
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


def _to_ready(db):
    """Walk a case to READY_TO_SHIP (PO committed to the supplier — the Gate-3 window)."""
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-26 09:00:00"); db.commit()
    seq = [
        ("availability_assessed", AG(), {"availability": {"requested_qty": 10, "in_stock": 4, "shortfall": 6}}),
        ("request_buyer_commitment", AG(), None),
        ("buyer_committed", BU(), None),
        ("external_message_drafted", AG(),
         {"draft": {"content_hash": "H1", "recipient_ref": "SUP-7",
                    "commercial_scope": {"quantity": 6, "item_ref": "LAP-021"}}}),
        ("approval_requested", AG(), None),
        ("approval_granted", HU(), None),
        ("external_message_sent", HU(), None),
        ("external_message_received", Actor(A.EXTERNAL, "s"), None),
        ("supplier_quote_validated", HU(),
         {"validated_quote": {"quoted_quantity": 6, "estimated_delivery_at": "2026-07-08",
                              "unit_amount_cents": 90000, "quote_expires_at": "2026-07-31", "confidence": 0.96}}),
    ]
    ts = 0
    for event, actor, patch in seq:
        ts += 1
        assert wf.transition(db, case_id=cid, event=event, actor=actor, state_patch=patch,
                             now_iso=f"2026-06-26 09:0{ts}:00").ok, event
    O.generate_and_record(db, case_id=cid, actor=AG(), local_delivery_at="2026-06-28", now_iso="2026-06-26 09:30:00")
    cur = wf.repository.current_version(db, cid)
    chosen = next(o for o in cur.state_json["options"] if o["option_type"] == O.OPTION_SHIP_TOGETHER)
    O.select_option(db, case_id=cid, actor=BU(), option_id=chosen["option_id"], now_iso="2026-06-26 10:00:00")
    PO.propose(db, case_id=cid, actor=AG(), now_iso="2026-06-26 10:05:00")
    PO.execute(db, case_id=cid, actor=HU(), idempotency_key="k1", today="2026-06-26", now_iso="2026-06-26 10:06:00")
    assert wf.current_state(db, cid) == S.READY_TO_SHIP
    return cid


# ── governance (pure domain) — the agent may PROPOSE, only a human may CANCEL ──
def test_agent_may_propose_but_only_human_may_cancel():
    for st in (S.PROCUREMENT_IN_PROGRESS, S.PARTIALLY_READY, S.READY_TO_SHIP):
        assert d.can_fire(st, "change_requested", AG())[0] is True    # agent/buyer/system/operator may PROPOSE
        assert d.can_fire(st, "change_requested", BU())[0] is True
        assert d.can_fire(st, "order_cancelled", AG())[0] is False     # agent may NOT execute the cancellation
        assert d.can_fire(st, "order_cancelled", BU())[0] is False
        assert d.can_fire(st, "order_cancelled", HU())[0] is True      # only a human executes
    # a COMPLETED order is terminal — no Gate-3 change (that would be a return, a separate flow)
    assert d.can_fire(S.COMPLETED, "change_requested", HU())[0] is False
    assert S.CANCELLED in d.TERMINAL_STATES


# ── economics (pure) ──────────────────────────────────────────────────────────
def test_assess_cancellation_surfaces_restock_and_penalty():
    a = CO.assess_cancellation(committed_cost_cents=540000, restock_fee_pct=0.15, supplier_penalty_cents=20000,
                               refundable_to_buyer_cents=600000)
    assert a["committed_cost_cents"] == 540000
    assert a["restock_fee_cents"] == 81000 and a["supplier_penalty_cents"] == 20000
    assert a["net_cancellation_cost_cents"] == 101000 and a["requires_human"] is True
    assert a["refundable_to_buyer_cents"] == 600000


# ── end-to-end: propose records, human cancels, original preserved, agent CANNOT cancel ──
def test_propose_records_without_changing_state(db):
    cid = _to_ready(db)
    res = CO.propose_change(db, case_id=cid, actor=AG(), kind=CO.KIND_CANCEL, reason="buyer_change")
    assert res.ok and wf.current_state(db, cid) == S.READY_TO_SHIP        # proposal does NOT move state
    sj = wf.repository.current_version(db, cid).state_json
    assert sj["change_request"]["status"] == "proposed" and sj["change_request"]["requires_human"] is True
    assert sj["change_request"]["assessment"]["committed_cost_cents"] == 540000  # economics on the record


def test_agent_cannot_authorize_cancellation_human_can(db):
    cid = _to_ready(db)
    bad = CO.authorize_cancellation(db, case_id=cid, actor=AG())   # an agent must NOT be able to cancel
    assert bad.ok is False and wf.current_state(db, cid) == S.READY_TO_SHIP   # nothing cancelled
    good = CO.authorize_cancellation(db, case_id=cid, actor=HU())  # a human authorises
    assert good.ok and wf.current_state(db, cid) == S.CANCELLED
    sj = wf.repository.current_version(db, cid).state_json
    assert sj["cancellation"]["refund_executed"] is False and sj["cancellation"]["authorised_by"] == "human_operator"
    # the original order data is PRESERVED bitemporally (append-only) — the PO is still on the record
    assert sj.get("purchase_order", {}).get("status") == "created"
