"""Tier-1 #5 review fix #1 — a DEFERRED (background) delivery must advance the case, not strand it.

When FULFILLMENT_OUTBOUND_QUEUE_ENABLED and the first send attempt fails transiently, the case sits in
APPROVED_TO_SEND with the message PENDING. When the background processor later delivers it, the case must
transition to QUOTE_SENT by REPLAYING the exact approved transition recorded on the queue row — never inventing
a new one, never leaving the case stranded.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.routers.fulfillment_cases import _replay_deferred_send_transitions
from src.app.services.fulfillment import draft as D
from src.app.services.fulfillment import outbound_queue as q
from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.domain import Actor, ActorType as AT, FulfillmentState as S


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def AG(): return Actor(AT.AGENT, "Procurement_Agent")
def BU(): return Actor(AT.BUYER, "u1")
def OP(): return Actor(AT.HUMAN_OPERATOR, "owner")


class _Res:
    def __init__(self, status, provider_ref=""):
        self.status, self.provider_ref, self.detail = status, provider_ref, "sandbox"


class _OkOnce:
    """Fails the first send (transient), succeeds after — models the deferred-delivery scenario."""
    def __init__(self):
        self.calls = 0

    def send(self, *, to, subject, body, idempotency_key=""):
        self.calls += 1
        return _Res("failed") if self.calls == 1 else _Res("sent", provider_ref="DEFERRED-PROV")


def _case_approved_to_send(db):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-28 09:00:00"); db.commit()
    wf.transition(db, case_id=cid, event="availability_assessed", actor=AG(),
                  state_patch={"availability": {"shortfall": 6, "requested_qty": 6, "in_stock": 0},
                               "requirements": {"use_case": "office", "needed_by": "2026-08-01",
                                                "ship_to": "Sydney NSW 2000"}}, now_iso="2026-06-28 09:00:01")
    wf.transition(db, case_id=cid, event="request_buyer_commitment", actor=AG(), now_iso="2026-06-28 09:00:02")
    wf.transition(db, case_id=cid, event="buyer_committed", actor=BU(), now_iso="2026-06-28 09:00:03")
    D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6, estimated_value_cents=100000,
                       rank_fn=lambda db, item, t: [{"id": "S7", "domain": "ok.example", "reliability": 0.9}],
                       allowlist_fn=lambda d: True, now_iso="2026-06-28 09:00:04")
    D.request_supplier_approval(db, case_id=cid, actor=AG(), now_iso="2026-06-28 09:00:05")
    wf.transition(db, case_id=cid, event="approval_granted", actor=OP(), reason_code="human_approved",
                  now_iso="2026-06-28 09:00:06")
    assert wf.current_state(db, cid) == S.APPROVED_TO_SEND
    return cid


def test_deferred_delivery_advances_case_not_strands_it(db):
    cid = _case_approved_to_send(db)
    # the human-approved send intent is enqueued; the FIRST attempt fails → case stays APPROVED_TO_SEND, pending.
    q.send_now(db, case_id=cid, recipient="s@ok.example", subject="RFQ", body="...", idempotency_key="hash-x",
               transport=_OkOnce(), actor_type="human_operator", actor_id="owner",
               transition_event="external_message_sent", now_iso="2026-06-28 09:01:00")
    assert wf.current_state(db, cid) == S.APPROVED_TO_SEND  # not sent yet — durably pending

    # the BACKGROUND processor delivers it later, then the router replays the approved transition.
    out = q.process_pending(db, transport=_AlwaysOk(), now_iso="2026-06-28 12:00:00")
    assert out["sent"] == 1
    rep = _replay_deferred_send_transitions(db, out["sent_rows"])
    assert rep["advanced"] == 1
    assert wf.current_state(db, cid) == S.QUOTE_SENT  # the case advanced — no stranding


def test_replay_is_idempotent_for_already_advanced_case(db):
    cid = _case_approved_to_send(db)
    q.send_now(db, case_id=cid, recipient="s@ok.example", subject="RFQ", body="...", idempotency_key="hash-y",
               transport=_AlwaysOk(), actor_type="human_operator", actor_id="owner",
               transition_event="external_message_sent", now_iso="2026-06-28 09:01:00")
    # the synchronous path already advanced the case in external_comms; replaying the same row must NOT re-fire.
    sent_rows = [{"case_id": cid, "content_hash": "hash-y", "provider_ref": "P",
                  "actor_type": "human_operator", "actor_id": "owner",
                  "transition_event": "external_message_sent"}]
    # simulate the case already at QUOTE_SENT (synchronous send did it)
    wf.transition(db, case_id=cid, event="external_message_sent", actor=OP(), reason_code="x",
                  now_iso="2026-06-28 09:02:00")
    assert wf.current_state(db, cid) == S.QUOTE_SENT
    rep = _replay_deferred_send_transitions(db, sent_rows)
    assert rep["advanced"] == 0 and rep["skipped"] == 1  # guard refused — no double transition


class _AlwaysOk:
    def send(self, *, to, subject, body, idempotency_key=""):
        return _Res("sent", provider_ref="DEFERRED-PROV")
