"""Amend-diff (#5) — the by-order amendment history + draft-diff (what changed between supplier drafts)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import cart_commitment as cc
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


def AG(): return Actor(A.AGENT, "agent")
def BU(): return Actor(A.BUYER, "u1")


def test_draft_diff_reports_what_changed():
    old = {"recipient_domain": "northbridge.example", "subject": "RFQ 10 laptops", "body": "x", "content_hash": "H1"}
    new = {"recipient_domain": "creatorfleet.example", "subject": "RFQ 12 laptops", "body": "y", "content_hash": "H2"}
    d = cc.draft_diff(old, new)
    assert d["changed"] is True and d["body_changed"] is True
    assert set(d["changed_fields"]) == {"recipient_domain", "subject", "content_hash"}
    assert d["fields"]["recipient_domain"] == {"from": "northbridge.example", "to": "creatorfleet.example"}
    assert d["prior_content_hash"] == "H1" and d["new_content_hash"] == "H2"


def test_draft_diff_no_change():
    same = {"subject": "RFQ", "body": "b", "content_hash": "H"}
    assert cc.draft_diff(same, dict(same))["changed"] is False


def _case(db, group, draft, *, supersede=False, ts="01"):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso=f"2026-06-30 09:{ts}:00"); db.commit()
    wf.transition(db, case_id=cid, event="availability_assessed", actor=AG(),
                  state_patch={"order_group_id": group, "availability": {"shortfall": 6}, "draft": draft},
                  now_iso=f"2026-06-30 09:{ts}:01")
    if supersede:
        wf.transition(db, case_id=cid, event="case_superseded", actor=BU(), now_iso=f"2026-06-30 09:{ts}:02")
    return cid


def test_list_order_cases_shows_active_and_superseded_with_diff(db):
    grp = "order-PR-x"
    # an earlier (superseded) version routed to Northbridge, then the active version re-routed to CreatorFleet
    _case(db, grp, {"subject": "RFQ v1", "recipient_domain": "northbridge.example", "content_hash": "H1",
                    "body": "10 units"}, supersede=True, ts="01")
    _case(db, grp, {"subject": "RFQ v2", "recipient_domain": "creatorfleet.example", "content_hash": "H2",
                    "body": "12 units"}, ts="05")
    cases = cc.list_order_cases(db, "PR-x", include_body=True)
    assert len(cases) == 2
    active = [c for c in cases if not c["superseded"]]
    superseded = [c for c in cases if c["superseded"]]
    assert len(active) == 1 and len(superseded) == 1
    assert active[0]["draft"]["recipient_domain"] == "creatorfleet.example"
    # the diff between the superseded and active drafts shows the re-route
    d = cc.draft_diff(superseded[0]["draft"], active[0]["draft"])
    assert "recipient_domain" in d["changed_fields"] and "content_hash" in d["changed_fields"]
    assert d["body_changed"] is True

    summary = cc.list_order_cases(db, "PR-x")
    assert "body" not in summary[0]["draft"]
