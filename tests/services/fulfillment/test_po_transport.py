"""PO→ERP transport seam (Phase-8) — sandbox default, HTTP-ERP adapter (fake client), selection, and
purchase_order.execute routing through it (an ERP failure records NO creation; replay → one PO)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import options as O
from src.app.services.fulfillment import po_transport as PT
from src.app.services.fulfillment import purchase_order as PO
from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.domain import Actor, ActorType as A, FulfillmentState as S


# ── unit: transports + selection ─────────────────────────────────────────────
def test_sandbox_creates_ref_no_real_system():
    r = PT.SandboxPoTransport().create(item_ref="LAP-021", quantity=6, idempotency_key="k-create")
    assert r.status == "created" and r.po_ref.startswith("PO-") and r.detail == "sandbox"


def test_get_po_transport_default_and_erp(monkeypatch):
    monkeypatch.delenv("FULFILLMENT_PO_TRANSPORT", raising=False)
    assert isinstance(PT.get_po_transport(), PT.SandboxPoTransport)
    monkeypatch.setenv("FULFILLMENT_PO_TRANSPORT", "erp")
    assert isinstance(PT.get_po_transport(), PT.HttpErpTransport)


class _FakeResp:
    def __init__(self, data): self._d = data
    def json(self): return self._d


class _FakeClient:
    def __init__(self): self.calls = []
    def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResp({"po_ref": "ERP-REAL-7"})


def test_erp_posts_and_returns_ref():
    c = _FakeClient()
    tx = PT.HttpErpTransport(url="https://erp.example/po", api_key="K", client=c)
    r = tx.create(supplier_ref="SUP-7", item_ref="LAP-021", quantity=6, unit_amount_cents=90000,
                  total_amount_cents=540000, idempotency_key="po-1-create")
    assert r.status == "created" and r.po_ref == "ERP-REAL-7" and r.detail == "erp"
    sent = c.calls[-1]
    assert sent["url"] == "https://erp.example/po"
    assert sent["headers"]["X-Idempotency-Key"] == "po-1-create"
    assert sent["headers"]["Authorization"] == "Bearer K" and sent["json"]["item_ref"] == "LAP-021"


def test_erp_no_url_fails():
    assert PT.HttpErpTransport(url="").create(item_ref="x").status == "failed"


def test_erp_client_error_is_status_failed():
    class _Boom:
        def post(self, *a, **k): raise OSError("erp down")
    r = PT.HttpErpTransport(url="https://erp.example/po", client=_Boom()).create(item_ref="x")
    assert r.status == "failed" and "erp down" in r.detail


# ── execute routes through the transport ─────────────────────────────────────
@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def _to_selected(db):
    AG = Actor(A.AGENT, "Procurement_Agent"); BU = Actor(A.BUYER, "u1"); HU = Actor(A.HUMAN_OPERATOR, "op")
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T", requested_by="u1",
                       now_iso="2026-06-27 09:00:00"); db.commit()
    seq = [
        ("availability_assessed", AG, {"availability": {"requested_qty": 10, "in_stock": 4, "shortfall": 6}}),
        ("request_buyer_commitment", AG, None), ("buyer_committed", BU, None),
        ("external_message_drafted", AG, {"draft": {"content_hash": "H1", "commercial_scope": {"quantity": 6}}}),
        ("approval_requested", AG, None), ("approval_granted", HU, None), ("external_message_sent", HU, None),
        ("external_message_received", Actor(A.EXTERNAL, "s"), None),
        ("supplier_quote_validated", HU, {"validated_quote": {"quoted_quantity": 6, "unit_amount_cents": 90000,
                                                              "estimated_delivery_at": "2026-07-08", "confidence": 0.9}}),
    ]
    ts = 0
    for ev, ac, patch in seq:
        ts += 1
        assert wf.transition(db, case_id=cid, event=ev, actor=ac, state_patch=patch,
                             now_iso=f"2026-06-27 09:0{ts}:00").ok, ev
    O.generate_and_record(db, case_id=cid, actor=AG, unit_price_cents=120000, now_iso="2026-06-27 09:30:00")
    chosen = next(o for o in wf.repository.current_version(db, cid).state_json["options"]
                  if o["option_type"] == O.OPTION_SHIP_TOGETHER)
    O.select_option(db, case_id=cid, actor=BU, option_id=chosen["option_id"], now_iso="2026-06-27 10:00:00")
    return cid, HU


def test_execute_sandbox_creates_po(db):
    cid, HU = _to_selected(db)
    PO.propose(db, case_id=cid, actor=Actor(A.AGENT, "Procurement_Agent"), now_iso="2026-06-27 10:05:00")
    r = PO.execute(db, case_id=cid, actor=HU, idempotency_key="k1", today="2026-06-27")  # default sandbox
    assert r.ok and wf.current_state(db, cid) == S.READY_TO_SHIP
    po = wf.repository.current_version(db, cid).state_json["purchase_order"]
    assert po["po_ref"].startswith("PO-") and po["sandbox"] is True


def test_execute_erp_failure_records_no_po(db):
    cid, HU = _to_selected(db)
    PO.propose(db, case_id=cid, actor=Actor(A.AGENT, "Procurement_Agent"), now_iso="2026-06-27 10:05:00")

    class _FailTx:
        def create(self, **kw): return PT.PoResult(po_ref="", status="failed", detail="erp down")

    r = PO.execute(db, case_id=cid, actor=HU, idempotency_key="k1", today="2026-06-27", po_transport=_FailTx())
    assert r.ok is False and r.reason == "po_create_failed"
    assert wf.current_state(db, cid) == S.PROCUREMENT_IN_PROGRESS  # approved but not created — retryable


def test_execute_is_idempotent_one_po_even_via_erp(db):
    cid, HU = _to_selected(db)
    PO.propose(db, case_id=cid, actor=Actor(A.AGENT, "Procurement_Agent"), now_iso="2026-06-27 10:05:00")

    class _CountTx:
        n = 0
        def create(self, **kw):
            _CountTx.n += 1
            return PT.PoResult(po_ref="ERP-1", status="created", detail="erp")

    PO.execute(db, case_id=cid, actor=HU, idempotency_key="same", today="2026-06-27", po_transport=_CountTx())
    PO.execute(db, case_id=cid, actor=HU, idempotency_key="same", today="2026-06-27", po_transport=_CountTx())
    assert _CountTx.n == 1  # the replay guard skipped the second ERP create
    assert wf.current_state(db, cid) == S.READY_TO_SHIP
