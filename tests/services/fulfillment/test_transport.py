"""Supplier-email transport seam (Phase-8) — sandbox default, SMTP adapter (fake client), selection,
and send_approved routing through it (a transport failure records NO send)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import external_comms as ec
from src.app.services.fulfillment import transport as T
from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.domain import Actor, ActorType as A, FulfillmentState as S


# ── sandbox (default) ─────────────────────────────────────────────────────────
def test_sandbox_stages_and_sends_nothing():
    r = T.SandboxTransport().send(to="approved-supplier.example", subject="s", body="b", idempotency_key="H1")
    assert r.status == "sent" and r.provider_ref.startswith("DEMO-OUT-") and r.detail == "sandbox"


def test_get_transport_defaults_to_sandbox(monkeypatch):
    monkeypatch.delenv("FULFILLMENT_SUPPLIER_TRANSPORT", raising=False)
    assert isinstance(T.get_transport(), T.SandboxTransport)


def test_get_transport_smtp_when_flagged(monkeypatch):
    monkeypatch.setenv("FULFILLMENT_SUPPLIER_TRANSPORT", "smtp")
    assert isinstance(T.get_transport(), T.SmtpTransport)


# ── SMTP adapter (fake client — no real network) ─────────────────────────────
class _FakeSMTP:
    sent: list = []

    def __init__(self, host, port):
        self.host, self.port = host, port

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        _FakeSMTP.sent.append(msg)

    def quit(self):
        pass


def test_smtp_builds_and_sends_message():
    _FakeSMTP.sent = []
    tx = T.SmtpTransport(host="mail.example", sender="proc@shopsquire.example", client_factory=_FakeSMTP)
    r = tx.send(to="ap@approved-supplier.example", subject="Quote request", body="Please quote.",
                idempotency_key="HASH123456")
    assert r.status == "sent" and r.provider_ref.startswith("SMTP-") and r.detail == "smtp"
    msg = _FakeSMTP.sent[-1]
    assert msg["To"] == "ap@approved-supplier.example" and msg["Subject"] == "Quote request"
    assert msg["X-Idempotency-Key"] == "HASH123456" and "Please quote." in msg.get_content()


def test_smtp_send_failure_is_status_failed():
    def _boom(host, port):
        raise OSError("connection refused")
    r = T.SmtpTransport(host="x", client_factory=_boom).send(to="a@b.example", subject="s", body="b")
    assert r.status == "failed" and r.provider_ref == "" and "connection refused" in r.detail


def test_smtp_no_recipient_fails():
    assert T.SmtpTransport(client_factory=_FakeSMTP).send(to="", subject="s", body="b").status == "failed"


# ── send_approved routes through the transport ───────────────────────────────
@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _to_approved_to_send(db):
    """Walk a case to APPROVED_TO_SEND with a draft (content_hash 'H1')."""
    AG = Actor(A.AGENT, "Procurement_Agent"); BU = Actor(A.BUYER, "u1"); HU = Actor(A.HUMAN_OPERATOR, "op")
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T", requested_by="u1",
                       now_iso="2026-06-27 09:00:00"); db.commit()
    seq = [
        ("availability_assessed", AG, {"availability": {"requested_qty": 10, "in_stock": 4, "shortfall": 6}}),
        ("request_buyer_commitment", AG, None), ("buyer_committed", BU, None),
        ("external_message_drafted", AG, {"draft": {"content_hash": "H1", "recipient_domain": "approved-supplier.example",
                                                    "subject": "s", "body": "b"}}),
        ("approval_requested", AG, None), ("approval_granted", HU, None),
    ]
    ts = 0
    for ev, ac, patch in seq:
        ts += 1
        assert wf.transition(db, case_id=cid, event=ev, actor=ac, state_patch=patch,
                             now_iso=f"2026-06-27 09:0{ts}:00").ok, ev
    assert wf.current_state(db, cid) == S.APPROVED_TO_SEND
    return cid, HU


def test_send_approved_sandbox_records_a_send(db):
    cid, HU = _to_approved_to_send(db)
    res = ec.send_approved(db, case_id=cid, actor=HU, approval_content_hash="H1")  # default sandbox
    assert res.ok and wf.current_state(db, cid) == S.QUOTE_SENT
    assert wf.repository.current_version(db, cid).state_json["outbound"]["provider_ref"].startswith("DEMO-OUT-")


def test_send_approved_records_no_send_on_transport_failure(db):
    cid, HU = _to_approved_to_send(db)

    class _FailTx:
        def send(self, **kw):
            return T.SendResult(provider_ref="", status="failed", detail="smtp down")

    res = ec.send_approved(db, case_id=cid, actor=HU, approval_content_hash="H1", transport=_FailTx())
    assert res.ok is False and res.reason == "send_failed"
    assert wf.current_state(db, cid) == S.APPROVED_TO_SEND  # no send recorded — the human can retry
