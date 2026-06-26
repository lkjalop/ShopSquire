"""Step 2 — the durable workflow enforces the contract at runtime.

Every command goes through transition(): illegal/disallowed → rejected (no state change), confidence-
gated transitions authorize, each accepted command writes a bitemporal version + is idempotent. This is
the layer the API/buttons sit on — if these hold, wiring a button is mechanical.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import repository as repo
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
def EX(): return Actor(A.EXTERNAL, "supplier-sys")
def SY(): return Actor(A.SYSTEM, "batch")


# (event, actor, now_iso) — the happy path with controllable business timestamps
_HAPPY = [
    ("availability_assessed", AG(), "2026-06-26 09:14:00"),
    ("request_buyer_commitment", AG(), "2026-06-26 09:14:05"),
    ("buyer_committed", BU(), "2026-06-26 09:20:00"),
    ("external_message_drafted", AG(), "2026-06-26 09:20:10"),
    ("approval_requested", AG(), "2026-06-26 09:20:15"),
    ("approval_granted", HU(), "2026-06-26 09:25:00"),
    ("external_message_sent", HU(), "2026-06-26 09:25:05"),
    ("external_message_received", EX(), "2026-06-26 09:40:00"),
    ("supplier_quote_validated", HU(), "2026-06-26 09:45:00"),
    ("fulfillment_options_generated", AG(), "2026-06-26 09:45:10"),
    ("buyer_fulfillment_selected", BU(), "2026-06-26 10:00:00"),
    ("purchase_order_proposed", AG(), "2026-06-26 10:00:05"),
    ("purchase_order_approved", HU(), "2026-06-26 10:05:00"),
    ("purchase_order_created", HU(), "2026-06-26 10:05:10"),
    ("completed", SY(), "2026-06-26 10:30:00"),
]


def _open(db):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="TRACE-1", requested_by="u1",
                       now_iso="2026-06-26 09:13:00")
    db.commit()
    return cid


def test_happy_path_persists_and_advances(db):
    cid = _open(db)
    assert wf.current_state(db, cid) == S.NEW
    for event, actor, ts in _HAPPY:
        r = wf.transition(db, case_id=cid, event=event, actor=actor, now_iso=ts,
                          evidence={"e": event}, reason_code=f"rc-{event}")
        assert r.ok, f"{event} by {actor.type}: {r.reason}"
    assert wf.current_state(db, cid) == S.COMPLETED
    # full history preserved (case_opened + 15 transitions)
    assert len(wf.journey(db, cid)) == 16


def test_disallowed_actor_is_rejected_403_no_state_change(db):
    cid = _open(db)
    # walk to APPROVED_TO_SEND
    for event, actor, ts in _HAPPY[:6]:
        assert wf.transition(db, case_id=cid, event=event, actor=actor, now_iso=ts).ok
    assert wf.current_state(db, cid) == S.APPROVED_TO_SEND
    # an AGENT tries to fire the human-only send
    r = wf.transition(db, case_id=cid, event="external_message_sent", actor=AG())
    assert r.ok is False and r.reason == "actor_not_permitted" and r.http_status == 403
    assert wf.current_state(db, cid) == S.APPROVED_TO_SEND  # unchanged


def test_illegal_transition_is_rejected_409(db):
    cid = _open(db)
    r = wf.transition(db, case_id=cid, event="external_message_sent", actor=HU())  # can't send from NEW
    assert r.ok is False and r.reason == "illegal_transition" and r.http_status == 409
    assert wf.current_state(db, cid) == S.NEW


def test_buyer_commitment_gate_blocks_agent_engagement(db):
    cid = _open(db)
    assert wf.transition(db, case_id=cid, event="availability_assessed", actor=AG()).ok
    # an agent cannot draft (engage a supplier) straight from assessment — no commitment yet
    r = wf.transition(db, case_id=cid, event="external_message_drafted", actor=AG())
    assert r.ok is False and r.reason == "illegal_transition"
    assert wf.current_state(db, cid) == S.AVAILABILITY_ASSESSED


def test_confidence_gate_denies_low_confidence_engage(db, monkeypatch):
    monkeypatch.setenv("ADAPTIVE_MIN_CONFIDENCE", "0.7")
    cid = _open(db)
    for event, actor, ts in _HAPPY[:3]:  # → COMMITTED
        assert wf.transition(db, case_id=cid, event=event, actor=actor, now_iso=ts).ok
    before = len(wf.journey(db, cid))
    r = wf.transition(db, case_id=cid, event="external_message_drafted", actor=AG(), confidence=0.5)
    assert r.ok is False and r.reason == "gate:low_confidence" and r.http_status == 403
    assert wf.current_state(db, cid) == S.COMMITTED          # not advanced
    assert len(wf.journey(db, cid)) == before                # no version written
    # sufficient confidence proceeds
    assert wf.transition(db, case_id=cid, event="external_message_drafted", actor=AG(), confidence=0.9).ok
    assert wf.current_state(db, cid) == S.QUOTE_DRAFTED


def test_idempotent_send_does_not_double_apply(db):
    cid = _open(db)
    for event, actor, ts in _HAPPY[:6]:  # → APPROVED_TO_SEND
        assert wf.transition(db, case_id=cid, event=event, actor=actor, now_iso=ts).ok
    r1 = wf.transition(db, case_id=cid, event="external_message_sent", actor=HU(), idempotency_key="SEND-1")
    r2 = wf.transition(db, case_id=cid, event="external_message_sent", actor=HU(), idempotency_key="SEND-1")
    assert r1.ok and r1.reason == "ok"
    assert r2.ok and r2.reason == "idempotent_replay" and r2.version_id == r1.version_id
    assert wf.current_state(db, cid) == S.QUOTE_SENT  # applied exactly once


def test_bitemporal_as_of_reconstructs_past_state(db):
    cid = _open(db)
    for event, actor, ts in _HAPPY[:7]:  # through external_message_sent (09:25:05) → QUOTE_SENT
        assert wf.transition(db, case_id=cid, event=event, actor=actor, now_iso=ts).ok
    # QUOTE_DRAFTED was valid only [09:20:10, 09:20:15) — the bitemporal read reconstructs it
    assert wf.as_of(db, cid, "2026-06-26 09:20:12").state == S.QUOTE_DRAFTED.value
    # AWAITING_APPROVAL was valid [09:20:15, 09:25:00)
    assert wf.as_of(db, cid, "2026-06-26 09:21:00").state == S.AWAITING_APPROVAL.value
    # at 09:14:02 it was only availability-assessed
    assert wf.as_of(db, cid, "2026-06-26 09:14:02").state == S.AVAILABILITY_ASSESSED.value
    # now → current
    assert wf.current_state(db, cid) == S.QUOTE_SENT


def test_state_json_accumulates_across_transitions(db):
    cid = _open(db)
    wf.transition(db, case_id=cid, event="availability_assessed", actor=AG(),
                  state_patch={"shortfall": 6}, now_iso="2026-06-26 09:14:00")
    wf.transition(db, case_id=cid, event="request_buyer_commitment", actor=AG(),
                  state_patch={"asked": True}, now_iso="2026-06-26 09:14:05")
    cur = repo.current_version(db, cid)
    assert cur.state_json.get("shortfall") == 6 and cur.state_json.get("asked") is True  # merged


def test_unknown_case_is_not_found(db):
    r = wf.transition(db, case_id="nope", event="availability_assessed", actor=AG())
    assert r.ok is False and r.reason == "not_found" and r.http_status == 404
