"""Bounded-autonomy buyer status reply: a claim-safe, commitment-free message per case state, so the
buyer always knows where their bulk request stands. Never contains a price/commitment (defense-in-depth)."""
from __future__ import annotations

import pytest

from src.app.services.fulfillment.buyer_reply import buyer_status_message

_CS = {"availability": {"requested_qty": 50}}


@pytest.mark.parametrize("state,needle", [
    ("AWAITING_BUYER_COMMITMENT", "Confirm sourcing"),
    ("COMMITTED", "no order has been placed"),
    ("QUOTE_SENT", "requested a quote"),
    ("OPTIONS_READY", "options are ready"),
    ("NO_APPROVED_SUPPLIER", "alternatives"),
    ("BUYER_DECLINED", "closed"),
])
def test_status_message_per_state(state, needle):
    msg = buyer_status_message(state, _CS)
    assert needle.lower() in msg.lower()


def test_includes_quantity_when_known():
    assert "50 units" in buyer_status_message("AWAITING_BUYER_COMMITMENT", _CS)


def test_never_contains_price_or_commitment():
    for state in ("AWAITING_BUYER_COMMITMENT", "COMMITTED", "QUOTE_SENT", "QUOTE_VALIDATED",
                  "OPTIONS_READY", "COMPLETED", "NO_APPROVED_SUPPLIER"):
        m = buyer_status_message(state, _CS).lower()
        assert "$" not in m and "guarantee" not in m and "purchase order" not in m


def test_unknown_state_is_empty():
    assert buyer_status_message("SOME_INTERNAL_STATE", _CS) == ""
    assert buyer_status_message(None, None) == ""


def test_supplier_closed_status_pauses_clock_without_promising_a_reply_date():
    msg = buyer_status_message("QUOTE_SENT", {
        **_CS,
        "supplier_response_expectation": {
            "calendar_state": "closed", "sla_clock": "paused",
            "next_open_at": "2026-08-10T23:00:00Z",
        },
    })
    assert "response clock is paused" in msg.lower()
    assert "next operating window" in msg.lower()
    assert "2026-08-10" not in msg


def test_unknown_supplier_calendar_is_explicitly_unverified():
    msg = buyer_status_message("QUOTE_SENT", {
        **_CS,
        "supplier_response_expectation": {"calendar_state": "unknown"},
    })
    assert "timing is not yet verified" in msg.lower()
    assert "no reply date is promised" in msg.lower()


# ── bounded-autonomy send (claim-safe buyer notification over the transport seam) ──
import pytest as _pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.app.services.fulfillment import workflow as _wf  # noqa: E402
from src.app.services.fulfillment.buyer_reply import send_buyer_status  # noqa: E402
from src.app.services.fulfillment.domain import Actor as _Actor, ActorType as _AT  # noqa: E402


class _Sent:
    status, provider_ref, detail = "sent", "BUYER-MSG-1", "sandbox"


class _FakeTx:
    def __init__(self): self.calls = []
    def send(self, *, to, subject, body, idempotency_key=""):
        self.calls.append({"to": to, "body": body, "key": idempotency_key}); return _Sent()


@_pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _committed(db):
    cid = _wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                        now_iso="2026-06-29 09:00:00"); db.commit()
    _wf.transition(db, case_id=cid, event="availability_assessed", actor=_Actor(_AT.AGENT, "a"),
                   state_patch={"availability": {"shortfall": 6, "requested_qty": 50, "in_stock": 44}},
                   now_iso="2026-06-29 09:00:01")
    _wf.transition(db, case_id=cid, event="request_buyer_commitment", actor=_Actor(_AT.AGENT, "a"),
                   now_iso="2026-06-29 09:00:02")
    _wf.transition(db, case_id=cid, event="buyer_committed", actor=_Actor(_AT.BUYER, "u1"),
                   now_iso="2026-06-29 09:00:03")
    return cid


def test_send_disabled_by_default(db):
    cid = _committed(db)
    assert send_buyer_status(db, cid, to_email="b@x.example", transport=_FakeTx())["reason"] == "disabled"


def test_force_sends_claim_safe_status(db):
    cid = _committed(db)
    tx = _FakeTx()
    out = send_buyer_status(db, cid, to_email="b@x.example", transport=tx, force=True)
    assert out["sent"] is True and out["state"] == "COMMITTED"
    body = tx.calls[0]["body"]
    assert "source the shortfall" in body.lower()  # the COMMITTED status
    assert "$" not in body and "purchase order" not in body.lower() and "guarantee" not in body.lower()  # claim-safe
    assert tx.calls[0]["key"] == f"buyer-status:{cid}:COMMITTED"  # idempotent per (case, state)


def test_no_recipient(db):
    cid = _committed(db)
    assert send_buyer_status(db, cid, to_email=None, transport=_FakeTx(), force=True)["reason"] == "no_recipient"
