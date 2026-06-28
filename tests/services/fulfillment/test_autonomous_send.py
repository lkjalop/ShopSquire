"""WS-C — autonomous RFQ send is a flag-gated, SAFE-FIRST policy gate.

The invariants: autonomy is OFF by default (→ escalate to the human); a kill switch, an untrusted recipient,
an unsafe or incomplete draft, low confidence, an over-cap value/quantity, or the per-hour rate limit each
ESCALATE (the case stays at AWAITING_APPROVAL for the human, untouched). Only when EVERY guard passes does
the agent autonomously approve + send — through DISTINCT autonomous transitions (the human-only GATE 2 is
never fired by the agent), recorded in the durable action audit.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import adaptive_action_gate as gate
from src.app.services.fulfillment import autonomous_send as A
from src.app.services.fulfillment import draft as D
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


def _rank_ok(db, item, t): return [{"id": "SUP-7", "domain": "approved-supplier.example", "reliability": 0.9}]
def _allow(domain): return domain == "approved-supplier.example"
def _kyv_ok(*, tenant_id, domain): return {"status": "verified", "risk_tier": "low"}
def _kyv_suspended(*, tenant_id, domain): return {"status": "suspended", "risk_tier": "low"}
def _kyv_high(*, tenant_id, domain): return {"status": "verified", "risk_tier": "high"}
def _kyv_none(*, tenant_id, domain): return None


class _Sent:
    status, provider_ref, detail = "sent", "AUTO-PROV-1", "sandbox"


class _FakeTransport:
    def send(self, *, to, subject, body, idempotency_key):
        return _Sent()


_COMPLETE_REQS = {"use_case": "office", "needed_by": "2026-08-01", "ship_to": "Sydney NSW 2000"}


def _case_awaiting_approval(db, *, reqs=_COMPLETE_REQS, qty=6, value=100000):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-26 09:00:00"); db.commit()
    patch = {"availability": {"shortfall": qty, "requested_qty": qty, "in_stock": 0}}
    if reqs:
        patch["requirements"] = reqs
    wf.transition(db, case_id=cid, event="availability_assessed", actor=AG(), state_patch=patch,
                  now_iso="2026-06-26 09:00:01")
    wf.transition(db, case_id=cid, event="request_buyer_commitment", actor=AG(), now_iso="2026-06-26 09:00:02")
    wf.transition(db, case_id=cid, event="buyer_committed", actor=BU(), now_iso="2026-06-26 09:00:03")
    D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=qty, estimated_value_cents=value,
                       rank_fn=_rank_ok, allowlist_fn=_allow, now_iso="2026-06-26 09:00:04")
    D.request_supplier_approval(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:00:05")
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL
    return cid


def _send(db, cid, *, confidence=0.95, value=100000, qty=6, kyv_fn=_kyv_ok):
    return A.maybe_autonomous_send(
        db, case_id=cid, actor=AG(), confidence=confidence, estimated_value_cents=value, quantity=qty,
        recipient_domain="approved-supplier.example", allowlist_fn=_allow, kyv_fn=kyv_fn,
        transport=_FakeTransport(), tenant_id="default", now_iso="2026-06-26 09:01:00")


# ── default-OFF: no flag → escalate, case untouched ──
def test_flag_off_escalates_and_leaves_case_for_human(db, monkeypatch):
    monkeypatch.delenv("FULFILLMENT_AUTONOMOUS_RFQ", raising=False)
    cid = _case_awaiting_approval(db)
    dec = _send(db, cid)
    assert dec.action == "escalated" and dec.reason == "flag_off"
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL  # the human still owns the send


# ── happy path: all guards pass → autonomous send via the AGENT-fired autonomous transitions ──
def test_all_guards_pass_sends_autonomously(db, monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RFQ", "1")
    cid = _case_awaiting_approval(db)
    dec = _send(db, cid)
    assert dec.action == "sent" and dec.reason == "autonomous_send"
    assert dec.provider_ref == "AUTO-PROV-1"
    assert wf.current_state(db, cid) == S.QUOTE_SENT
    # the action-gate authorized + audited the send as supplier_rfq_send
    audit = gate.load_recent_audit(db, tenant_id="default")
    assert any(a["action_type"] == "supplier_rfq_send" and a["decision"] == "allow" for a in audit)


def test_kill_switch_escalates(db, monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RFQ", "1")
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_KILL_SWITCH", "1")
    cid = _case_awaiting_approval(db)
    dec = _send(db, cid)
    assert dec.action == "escalated" and dec.reason == "killed"
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL


@pytest.mark.parametrize("kyv_fn", [_kyv_none, _kyv_suspended, _kyv_high])
def test_untrusted_recipient_escalates(db, monkeypatch, kyv_fn):
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RFQ", "1")
    cid = _case_awaiting_approval(db)
    dec = _send(db, cid, kyv_fn=kyv_fn)
    assert dec.action == "escalated" and dec.reason == "recipient_untrusted"
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL


def test_allowlist_miss_escalates(db, monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RFQ", "1")
    cid = _case_awaiting_approval(db)
    dec = A.maybe_autonomous_send(db, case_id=cid, actor=AG(), confidence=0.95, estimated_value_cents=100000,
                                  quantity=6, recipient_domain="approved-supplier.example",
                                  allowlist_fn=lambda d: False, kyv_fn=_kyv_ok, transport=_FakeTransport())
    assert dec.action == "escalated" and dec.reason == "recipient_untrusted"


def test_low_confidence_escalates(db, monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RFQ", "1")
    cid = _case_awaiting_approval(db)
    dec = _send(db, cid, confidence=0.5)  # < default 0.8
    assert dec.action == "escalated" and dec.reason == "low_confidence"
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL


def test_over_value_cap_escalates(db, monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RFQ", "1")
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_MAX_VALUE_CENTS", "500000")
    cid = _case_awaiting_approval(db, value=900000)
    dec = _send(db, cid, value=900000)  # $9,000 > $5,000 cap
    assert dec.action == "escalated" and dec.reason == "over_value_cap"


def test_over_qty_cap_escalates(db, monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RFQ", "1")
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_MAX_QTY", "25")
    cid = _case_awaiting_approval(db, qty=10)
    dec = _send(db, cid, qty=100)  # 100 > 25 cap
    assert dec.action == "escalated" and dec.reason == "over_qty_cap"


def test_incomplete_draft_escalates(db, monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RFQ", "1")
    # requirements without a real deadline → completeness flags deadline_date → must not auto-send
    cid = _case_awaiting_approval(db, reqs={"use_case": "office"})
    dec = _send(db, cid)
    assert dec.action == "escalated" and dec.reason.startswith("incomplete:")
    assert "deadline_date" in dec.reason
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL


def test_rate_limited_escalates(db, monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RFQ", "1")
    monkeypatch.setenv("FULFILLMENT_AUTONOMOUS_RATE_PER_HOUR", "2")
    cid = _case_awaiting_approval(db)
    gate.ensure_table(db)
    for i in range(2):  # two prior autonomous sends this hour → at the limit
        db.execute(text("INSERT INTO adaptive_action_audit (id, tenant_id, action_type, decision, confidence) "
                        "VALUES (:i,'default','supplier_rfq_send','allow',0.9)"), {"i": f"prior-{i}"})
    db.commit()
    dec = _send(db, cid)
    assert dec.action == "escalated" and dec.reason == "rate_limited"
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL
