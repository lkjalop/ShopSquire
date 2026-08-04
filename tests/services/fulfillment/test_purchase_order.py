"""PO finalization — the journey's last act after the buyer selects.

Proves: the AGENT proposes (never approves), the HUMAN approves+creates, a SANDBOX PO ref is recorded,
execute is IDEMPOTENT (one PO per double-click), and it REFUSES an expired quote or an out-of-scope
quantity — then the order reaches COMPLETED.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import options as O
from src.app.services.fulfillment import purchase_order as PO
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


def _to_selected(db, *, scope_qty: int = 6, unit_cents: int = 90000, expires: str = "2026-07-31"):
    """Walk a case all the way to SELECTED (buyer picked ship-together: 4 local + 6 supplier)."""
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-26 09:00:00"); db.commit()
    seq = [
        ("availability_assessed", AG(), {"availability": {"requested_qty": 10, "in_stock": 4, "shortfall": 6}}),
        ("request_buyer_commitment", AG(), None),
        ("buyer_committed", BU(), None),
        ("external_message_drafted", AG(),
         {"draft": {"content_hash": "H1", "recipient_ref": "SUP-7",
                    "commercial_scope": {"quantity": scope_qty, "item_ref": "LAP-021"}}}),
        ("approval_requested", AG(), None),
        ("approval_granted", HU(), None),
        ("external_message_sent", HU(), None),
        ("external_message_received", Actor(A.EXTERNAL, "s"), None),
        ("supplier_quote_validated", HU(),
         {"validated_quote": {"quoted_quantity": 6, "estimated_delivery_at": "2026-07-08",
                              "unit_amount_cents": unit_cents, "quote_expires_at": expires, "confidence": 0.96}}),
    ]
    ts = 0
    for event, actor, patch in seq:
        ts += 1
        assert wf.transition(db, case_id=cid, event=event, actor=actor, state_patch=patch,
                             now_iso=f"2026-06-26 09:0{ts}:00").ok, event
    O.generate_and_record(db, case_id=cid, actor=AG(), local_delivery_at="2026-06-28",
                          now_iso="2026-06-26 09:30:00")
    cur = wf.repository.current_version(db, cid)
    chosen = next(o for o in cur.state_json["options"] if o["option_type"] == O.OPTION_SHIP_TOGETHER)
    assert O.select_option(db, case_id=cid, actor=BU(), option_id=chosen["option_id"],
                           now_iso="2026-06-26 10:00:00").ok
    assert wf.current_state(db, cid) == S.SELECTED
    return cid


# ── happy path ────────────────────────────────────────────────────────────────
def test_full_finalization_reaches_completed(db):
    cid = _to_selected(db)
    assert PO.propose(db, case_id=cid, actor=AG(), now_iso="2026-06-26 10:05:00").ok
    assert wf.current_state(db, cid) == S.PROCUREMENT_APPROVAL_REQUIRED
    po = wf.repository.current_version(db, cid).state_json["purchase_order"]
    assert po["quantity"] == 6 and po["status"] == "proposed"           # supplier units only (not 10)
    assert po["total_amount_cents"] == 6 * 90000

    r = PO.execute(db, case_id=cid, actor=HU(), idempotency_key="k1", today="2026-06-26",
                   now_iso="2026-06-26 10:06:00")
    assert r.ok and wf.current_state(db, cid) == S.READY_TO_SHIP
    po = wf.repository.current_version(db, cid).state_json["purchase_order"]
    assert po["status"] == "created" and po["po_ref"].startswith("PO-") and po["sandbox"] is True

    assert PO.complete(db, case_id=cid, actor=HU(), now_iso="2026-06-26 10:07:00").ok
    assert wf.current_state(db, cid) == S.COMPLETED


# ── actor guards ─────────────────────────────────────────────────────────────
def test_propose_is_agent_only(db):
    cid = _to_selected(db)
    r = PO.propose(db, case_id=cid, actor=HU(), now_iso="2026-06-26 10:05:00")  # human can't propose
    assert r.ok is False and r.reason == "actor_not_permitted"
    assert wf.current_state(db, cid) == S.SELECTED  # unchanged


def test_execute_requires_proposed_first(db):
    cid = _to_selected(db)  # still SELECTED, no PO proposed
    r = PO.execute(db, case_id=cid, actor=HU(), idempotency_key="k1", today="2026-06-26")
    assert r.ok is False  # purchase_order_approved is illegal from SELECTED
    assert wf.current_state(db, cid) == S.SELECTED


# ── idempotency + guards ─────────────────────────────────────────────────────
def test_execute_is_idempotent(db):
    cid = _to_selected(db)
    PO.propose(db, case_id=cid, actor=AG(), now_iso="2026-06-26 10:05:00")
    r1 = PO.execute(db, case_id=cid, actor=HU(), idempotency_key="same", today="2026-06-26",
                    now_iso="2026-06-26 10:06:00")
    ref1 = wf.repository.current_version(db, cid).state_json["purchase_order"]["po_ref"]
    r2 = PO.execute(db, case_id=cid, actor=HU(), idempotency_key="same", today="2026-06-26",
                    now_iso="2026-06-26 10:06:30")
    ref2 = wf.repository.current_version(db, cid).state_json["purchase_order"]["po_ref"]
    assert r1.ok and r2.ok and ref1 == ref2  # exactly one PO created
    assert wf.current_state(db, cid) == S.READY_TO_SHIP


def test_execute_refuses_expired_quote(db):
    cid = _to_selected(db, expires="2026-06-20")  # quote already expired by today
    PO.propose(db, case_id=cid, actor=AG(), now_iso="2026-06-26 10:05:00")
    r = PO.execute(db, case_id=cid, actor=HU(), idempotency_key="k1", today="2026-06-26")
    assert r.ok is False and r.reason == "quote_expired"
    assert wf.current_state(db, cid) == S.PROCUREMENT_APPROVAL_REQUIRED  # not advanced


def test_execute_refuses_out_of_scope_quantity(db):
    cid = _to_selected(db, scope_qty=4)  # only 4 approved, but 6 supplier units selected
    PO.propose(db, case_id=cid, actor=AG(), now_iso="2026-06-26 10:05:00")
    r = PO.execute(db, case_id=cid, actor=HU(), idempotency_key="k1", today="2026-06-26")
    assert r.ok is False and r.reason == "out_of_scope"
    assert wf.current_state(db, cid) == S.PROCUREMENT_APPROVAL_REQUIRED
