"""Phase 3 — buyer qualification gates supplier contact. A human verifies the buyer is serious BEFORE any
RFQ is drafted; the verdict is recorded bitemporally; disqualified ends the case (no supplier contacted).
With FULFILLMENT_REQUIRE_QUALIFICATION on, draft_and_record refuses until the case is qualified."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import buyer_qualification as bq
from src.app.services.fulfillment import draft as D
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
def HU(): return Actor(A.HUMAN_OPERATOR, "owner")


def _rank_ok(db, item, t): return [{"id": "SUP-7", "domain": "approved-supplier.example", "reliability": 0.9}]
def _allow(domain): return domain == "approved-supplier.example"


def _committed(db):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-28 09:00:00"); db.commit()
    wf.transition(db, case_id=cid, event="availability_assessed", actor=AG(),
                  state_patch={"availability": {"shortfall": 6, "requested_qty": 10, "in_stock": 4}},
                  now_iso="2026-06-28 09:00:01")
    wf.transition(db, case_id=cid, event="request_buyer_commitment", actor=AG(), now_iso="2026-06-28 09:00:02")
    wf.transition(db, case_id=cid, event="buyer_committed", actor=BU(), now_iso="2026-06-28 09:00:03")
    return cid


def test_request_then_qualify_records_verdict_and_stays_committed(db):
    cid = _committed(db)
    bq.request_qualification(db, case_id=cid, actor=AG(), room_ref="INC-1")
    cur = wf.repository.current_version(db, cid)
    assert cur.state == S.COMMITTED.value and cur.state_json["qualification"]["status"] == "requested"
    assert cur.state_json["qualification"]["room_ref"] == "INC-1"
    res = bq.record_qualification(db, case_id=cid, actor=HU(), qualified=True, notes="confirmed PO budget")
    assert res.ok and bq.is_qualified(wf.repository.current_version(db, cid).state_json)


def test_disqualified_ends_the_case(db):
    cid = _committed(db)
    res = bq.record_qualification(db, case_id=cid, actor=HU(), qualified=False, notes="just browsing")
    assert res.ok and wf.current_state(db, cid) == S.BUYER_DECLINED


def test_qualified_only_by_human(db):
    cid = _committed(db)
    res = bq.record_qualification(db, case_id=cid, actor=AG(), qualified=True)  # agent can't qualify
    assert res.ok is False  # actor_not_permitted (buyer_qualified is HUMAN_OPERATOR-only)


def test_draft_blocked_until_qualified_when_required(db, monkeypatch):
    monkeypatch.setenv("FULFILLMENT_REQUIRE_QUALIFICATION", "1")
    cid = _committed(db)
    res, draft = D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6,
                                    rank_fn=_rank_ok, allowlist_fn=_allow, now_iso="2026-06-28 09:01:00")
    assert res.ok is False and res.reason == "buyer_not_qualified" and draft is None
    # qualify → draft now permitted
    bq.record_qualification(db, case_id=cid, actor=HU(), qualified=True)
    res2, draft2 = D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6,
                                      rank_fn=_rank_ok, allowlist_fn=_allow, now_iso="2026-06-28 09:02:00")
    assert res2.ok and draft2 is not None


def test_draft_not_blocked_when_qualification_off(db):
    cid = _committed(db)  # FULFILLMENT_REQUIRE_QUALIFICATION unset (default OFF)
    res, draft = D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6,
                                    rank_fn=_rank_ok, allowlist_fn=_allow, now_iso="2026-06-28 09:01:00")
    assert res.ok and draft is not None  # parity: no qualification required by default
