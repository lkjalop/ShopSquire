"""Competitive RFQ fan-out + quote comparison (multi-supplier procurement, Phase 1).

The fan-out builds a fully-caged draft per top-N approved supplier (same allowlist/claim-safety as the
single draft) and never sends; the comparator ranks returned quotes by a vertical-blind composite.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import draft as D
from src.app.services.fulfillment import rfq_fanout as RF


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


# three approved suppliers + one off-allowlist
def _rank_multi(db, item, t):
    return [
        {"id": "SUP-A", "domain": "a-supplier.example", "reliability": 0.95},
        {"id": "SUP-B", "domain": "b-supplier.example", "reliability": 0.85},
        {"id": "SUP-C", "domain": "c-supplier.example", "reliability": 0.80},
        {"id": "SUP-X", "domain": "evil.example", "reliability": 0.99},  # not on the allowlist
    ]


def _allow(domain):
    return domain in {"a-supplier.example", "b-supplier.example", "c-supplier.example"}


# ── fan-out builder ────────────────────────────────────────────────────────────
def test_fanout_drafts_one_per_top_n_approved_supplier(db):
    drafts = RF.build_rfq_fanout(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                                 top_n=3, rank_fn=_rank_multi, allowlist_fn=_allow)
    assert len(drafts) == 3
    domains = {d.recipient_domain for d in drafts}
    assert domains == {"a-supplier.example", "b-supplier.example", "c-supplier.example"}
    # every fan-out draft is caged: claim-safe body with the not-a-PO footer, no price leak
    for d in drafts:
        assert D.claim_safety_reason(d.body, recipient_domain=d.recipient_domain) is None


def test_fanout_respects_top_n_cap(db):
    drafts = RF.build_rfq_fanout(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                                 top_n=2, rank_fn=_rank_multi, allowlist_fn=_allow)
    assert len(drafts) == 2  # only the top 2 approved


def test_fanout_excludes_off_allowlist_suppliers(db):
    drafts = RF.build_rfq_fanout(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                                 top_n=8, rank_fn=_rank_multi, allowlist_fn=_allow)
    assert all(d.recipient_domain != "evil.example" for d in drafts)
    assert len(drafts) == 3  # the off-allowlist supplier is dropped even with headroom


def test_fanout_empty_when_no_approved_supplier(db):
    drafts = RF.build_rfq_fanout(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                                 top_n=3, rank_fn=_rank_multi, allowlist_fn=lambda d: False)
    assert drafts == []


def test_supplier_override_targets_a_specific_supplier(db):
    d = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                      supplier_override=("SUP-B", "b-supplier.example", 0.85, "chosen"))
    assert d is not None and d.recipient_domain == "b-supplier.example"


def test_fanout_preview_carries_send_gate(db):
    drafts = RF.build_rfq_fanout(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                                 top_n=3, rank_fn=_rank_multi, allowlist_fn=_allow)
    rows = RF.fanout_preview(drafts)
    assert len(rows) == 3
    for r in rows:
        assert r["recipient_domain"] and r["subject"] and r["body"]
        assert isinstance(r["send_gate"], dict) and "decision" in r["send_gate"]


# ── quote comparator (pure, vertical-blind) ─────────────────────────────────────
def _quotes():
    return [
        {"supplier_ref": "A", "recipient_domain": "a.example", "unit_price_cents": 120000, "lead_time_days": 10, "reliability": 0.95},
        {"supplier_ref": "B", "recipient_domain": "b.example", "unit_price_cents": 100000, "lead_time_days": 20, "reliability": 0.80},
        {"supplier_ref": "C", "recipient_domain": "c.example", "unit_price_cents": 110000, "lead_time_days": 7, "reliability": 0.90},
    ]


def test_compare_ranks_by_composite_and_recommends_best():
    r = RF.compare_quotes(_quotes())
    assert r["considered"] == 3 and r["excluded"] == 0
    # C: shortest lead + high reliability + near-cheapest → best composite by default weights
    assert r["recommended"]["supplier_ref"] == "C"
    assert r["ranked"][0]["supplier_ref"] == "C"
    assert "shortest_lead_time" in r["ranked"][0]["reasons"]
    # cheapest gets the lowest_unit_price tag
    b = next(n for n in r["ranked"] if n["supplier_ref"] == "B")
    assert "lowest_unit_price" in b["reasons"]


def test_compare_excludes_quotes_with_no_usable_price():
    q = _quotes() + [{"supplier_ref": "D", "unit_price_cents": 0}, {"supplier_ref": "E", "unit_price_cents": None}]
    r = RF.compare_quotes(q)
    assert r["considered"] == 3 and r["excluded"] == 2
    assert all(n["supplier_ref"] not in ("D", "E") for n in r["ranked"])


def test_compare_weights_can_prioritise_price():
    # weight price to 1.0 → cheapest (B) must win regardless of lead/reliability
    r = RF.compare_quotes(_quotes(), weights={"price": 1.0, "lead_time": 0.0, "reliability": 0.0})
    assert r["recommended"]["supplier_ref"] == "B"


def test_compare_empty_is_safe():
    assert RF.compare_quotes([]) == {"ranked": [], "recommended": None, "considered": 0, "excluded": 0}


def test_compare_handles_missing_lead_and_reliability():
    q = [{"supplier_ref": "A", "unit_price_cents": 100000},
         {"supplier_ref": "B", "unit_price_cents": 90000}]
    r = RF.compare_quotes(q)
    assert r["considered"] == 2
    assert r["recommended"]["supplier_ref"] == "B"  # cheaper wins; lead/reliability neutral when absent
