"""Step 3 — the supplier draft is an LLM-aid INSIDE A CAGE.

The invariants: recipient comes from the allowlist not buyer text; the body never leaks a price and
always carries the not-a-PO footer; evidence is scatter-gathered as discrete ids with provenance;
the content_hash pins the message and changes on edit; a price-injecting LLM is rejected; and the
whole thing flows through the workflow chokepoint (confidence-gated, bitemporal, traced).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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


# deterministic injectable evidence sources (no network)
def _rank_ok(db, item, t): return [{"id": "SUP-7", "domain": "approved-supplier.example", "reliability": 0.9}]
def _rank_untrusted(db, item, t): return [{"id": "SUP-X", "domain": "evil.example", "reliability": 0.9}]
def _allow(domain): return domain == "approved-supplier.example"
def _hippo(db, item, t): return [{"summary": "3 prior on-time deliveries", "label": "SUP-7"}]
def _market(db, item, t): return [{"finding_type": "demand_shift", "summary": "demand rising", "severity": "warn"}]
def _benchmark(item): return {"summary": "street price ~ benchmark", "source": "allowlisted-index"}


def _committed_case(db):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-26 09:00:00"); db.commit()
    wf.transition(db, case_id=cid, event="availability_assessed", actor=AG(),
                  state_patch={"availability": {"shortfall": 6, "requested_qty": 10, "in_stock": 4}},
                  now_iso="2026-06-26 09:00:01")
    wf.transition(db, case_id=cid, event="request_buyer_commitment", actor=AG(), now_iso="2026-06-26 09:00:02")
    wf.transition(db, case_id=cid, event="buyer_committed", actor=BU(), now_iso="2026-06-26 09:05:00")
    return cid


# ── the cage ─────────────────────────────────────────────────────────────────
def test_recipient_from_allowlist_never_from_buyer_text(db):
    # even though the "buyer query" names an attacker address, the recipient is the allowlisted supplier
    draft = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                          rank_fn=_rank_ok, allowlist_fn=_allow, hippograph_fn=_hippo, market_fn=_market)
    assert draft is not None
    assert draft.recipient_domain == "approved-supplier.example"
    assert "evil" not in draft.body.lower() and "attacker" not in draft.body.lower()


def test_no_approved_supplier_when_domain_not_allowlisted(db):
    assert D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                         rank_fn=_rank_untrusted, allowlist_fn=_allow) is None


def test_body_is_claim_safe_no_price_and_has_po_disclaimer(db):
    draft = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                          rank_fn=_rank_ok, allowlist_fn=_allow)
    assert "this request does not constitute a purchase order" in draft.body.lower()
    import re
    assert re.search(r"[$€£¥]\s?\d", draft.body) is None  # no price leak to the supplier


def test_price_injecting_llm_is_rejected(db):
    bad_llm = lambda *, subject, body, slots: {"subject": subject, "body": body + "\nWe will pay $900 each."}
    draft = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                          rank_fn=_rank_ok, allowlist_fn=_allow, llm_fn=bad_llm)
    assert "$900" not in draft.body  # the unsafe LLM output was discarded, deterministic fill kept


def test_evidence_scatter_gather_has_discrete_ids_and_provenance(db):
    draft = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                          case_state={"availability": {"shortfall": 6, "requested_qty": 10}},
                          rank_fn=_rank_ok, allowlist_fn=_allow, hippograph_fn=_hippo, market_fn=_market,
                          benchmark_fn=_benchmark)
    sources = {e["source"] for e in draft.evidence}
    assert {"inventory", "hippograph", "market_intel", "external_benchmark"} <= sources
    ext = next(e for e in draft.evidence if e["source"] == "external_benchmark")
    assert ext["provenance"].startswith("external:")  # provenance-tagged
    assert all(e["evidence_id"] for e in draft.evidence)
    assert any("on-time" in r for r in draft.rationale)  # rationale explains the supplier choice


def test_content_hash_changes_on_edit(db):
    d1 = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1", rank_fn=_rank_ok, allowlist_fn=_allow)
    d2 = D.build_draft(db, item_ref="SKU-1", quantity=99, case_ref="FC-1", rank_fn=_rank_ok, allowlist_fn=_allow)
    assert d1.content_hash != d2.content_hash  # an edit (qty change) → new hash → voids prior approval
    assert D.content_hash("a", "b") == D.content_hash("a", "b")  # deterministic


# ── flows through the workflow chokepoint ────────────────────────────────────
def test_draft_and_record_advances_to_quote_drafted_with_evidence(db):
    cid = _committed_case(db)
    res, draft = D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6,
                                    estimated_value_cents=669000, rank_fn=_rank_ok, allowlist_fn=_allow,
                                    hippograph_fn=_hippo, market_fn=_market, now_iso="2026-06-26 09:05:10")
    assert res.ok and wf.current_state(db, cid) == S.QUOTE_DRAFTED
    cur = wf.repository.current_version(db, cid)
    assert cur.state_json["draft"]["content_hash"] == draft.content_hash  # draft persisted on the case


def test_draft_and_record_fires_no_approved_supplier(db):
    cid = _committed_case(db)
    res, draft = D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6,
                                    rank_fn=_rank_untrusted, allowlist_fn=_allow, now_iso="2026-06-26 09:05:10")
    assert draft is None and wf.current_state(db, cid) == S.NO_APPROVED_SUPPLIER


def test_request_approval_advances_and_carries_hash(db):
    cid = _committed_case(db)
    D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6, rank_fn=_rank_ok,
                       allowlist_fn=_allow, now_iso="2026-06-26 09:05:10")
    # the AGENT submits the draft to the approval queue (the human later fires approval_granted)
    res, _approval_id = D.request_supplier_approval(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:05:20")
    assert res.ok and wf.current_state(db, cid) == S.AWAITING_APPROVAL
    # the approval_requested trace evidence carries the content_hash (best-effort enqueue may be None in unit db)
    cur = wf.repository.current_version(db, cid)
    assert cur.state_json["draft"]["content_hash"]


def HU(): return Actor(A.HUMAN_OPERATOR, "owner-01")


def _to_awaiting_approval(db):
    cid = _committed_case(db)
    D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6, rank_fn=_rank_ok,
                       allowlist_fn=_allow, now_iso="2026-06-26 09:05:10")
    D.request_supplier_approval(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:05:20")
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL
    return cid


def test_edit_draft_rehashes_and_voids_approval(db):
    cid = _to_awaiting_approval(db)
    before = wf.repository.current_version(db, cid).state_json["draft"]["content_hash"]
    res, draft = D.edit_draft(db, case_id=cid, actor=HU(),
                              body="Hello, please confirm availability.\n\nThis request does not "
                                   "constitute a purchase order.\n\nRegards", now_iso="2026-06-26 09:05:30")
    assert res.ok and wf.current_state(db, cid) == S.QUOTE_DRAFTED  # edit → back to DRAFTED (approval void)
    assert draft["content_hash"] != before                          # new hash → the stale approval can't send


def test_edit_draft_rejects_unsafe_body(db):
    cid = _to_awaiting_approval(db)
    res, draft = D.edit_draft(db, case_id=cid, actor=HU(), body="We will pay $1200 per unit.",
                              now_iso="2026-06-26 09:05:30")  # price leak + no PO footer
    assert res.ok is False and res.reason == "unsafe_edit" and draft is None
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL       # unchanged — unsafe edit refused


# ── supplier-expectation personalisation (deterministic, before any LLM polish) ──
def test_supplier_context_personalises_when_prior_history(db):
    # a supplier we've dealt with before gets a claim-safe relationship line; a new one does not.
    with_hist = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                              rank_fn=_rank_ok, allowlist_fn=_allow,
                              inbox_fn=lambda domain, t: {"observations": 3, "summary": "3 prior orders"})
    assert "continued partnership" in with_hist.body.lower()
    no_hist = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                            rank_fn=_rank_ok, allowlist_fn=_allow, inbox_fn=lambda domain, t: None)
    assert "continued partnership" not in no_hist.body.lower()
    # personalisation never breaks the cage
    assert "this request does not constitute a purchase order" in with_hist.body.lower()


# ── deterministic pre-send gate (governance, prior to the human GATE 2) ──
def _gate_draft(**over):
    base = {"recipient_email": "orders@approved-supplier.example", "recipient_domain": "approved-supplier.example",
            "body": "Hello. This request does not constitute a purchase order.", "confidence": 0.8,
            "commercial_scope": {"item_ref": "SKU-1", "quantity": 6}, "evidence": [{"evidence_id": "E1"}]}
    base.update(over)
    return base


def test_send_gate_allows_complete_safe_draft():
    g = D.draft_send_gate(_gate_draft())
    assert g["decision"] == "allow" and not g["blocking"] and not g["reasons"]


def test_send_gate_blocks_no_recipient_and_claim_leak():
    assert D.draft_send_gate(_gate_draft(recipient_email="", recipient_domain=""))["decision"] == "block"
    leak = D.draft_send_gate(_gate_draft(body="We will pay $900 each."))  # price leak + no PO footer
    assert leak["decision"] == "block" and "claim_unsafe" in leak["blocking"]


def test_send_gate_needs_info_when_incomplete():
    assert "missing_commercial_scope" in D.draft_send_gate(
        _gate_draft(commercial_scope={"item_ref": "", "quantity": 0}))["reasons"]
    assert "low_confidence" in D.draft_send_gate(_gate_draft(confidence=0.2))["reasons"]
    assert "no_evidence" in D.draft_send_gate(_gate_draft(evidence=[]))["reasons"]
    # needs_info, not block — it's recoverable by getting more info (incl. a supplier RFI)
    assert D.draft_send_gate(_gate_draft(confidence=0.2))["decision"] == "needs_info"


def test_draft_and_record_attaches_advisory_send_gate(db):
    cid = _committed_case(db)
    res, draft = D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6,
                                    rank_fn=_rank_ok, allowlist_fn=_allow, now_iso="2026-06-26 09:05:10")
    assert res.ok and draft is not None
    cur = wf.repository.current_version(db, cid)
    gate = (cur.state_json.get("draft") or {}).get("send_gate") or {}
    assert gate.get("decision") in ("allow", "needs_info", "block")


# ── way-1: buyer requirements cited in the RFQ (budget stays internal) ──
def test_requirements_block_renders_buyer_constraints_excluding_budget(db):
    cs = {"availability": {"shortfall": 6, "requested_qty": 10},
          "requirements": {"use_case": "office", "specs": ["16gb ram", "512gb ssd"],
                           "needed_within_days": 14, "budget": {"min": 1300, "max": 1500}}}
    draft = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1", case_state=cs,
                          rank_fn=_rank_ok, allowlist_fn=_allow)
    body = draft.body.lower()
    assert "key requirements" in body and "intended use: office" in body
    assert "16gb ram" in body and "needed within: 14 days" in body
    # budget is internal-only — it must never anchor supplier pricing
    assert "1300" not in draft.body and "1500" not in draft.body and "budget" not in body
    assert "this request does not constitute a purchase order" in body  # cage intact


def test_no_requirements_block_when_case_has_none(db):
    draft = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                          rank_fn=_rank_ok, allowlist_fn=_allow)
    assert "key requirements" not in draft.body.lower()


def test_supplier_greeting_uses_legal_name_when_resolvable(db, monkeypatch):
    monkeypatch.setattr("src.app.security.kyv_registry.lookup_vendor_by_domain",
                        lambda *, tenant_id, domain: {"legal_name": "TechData Procurement"})
    draft = D.build_draft(db, item_ref="SKU-1", quantity=6, case_ref="FC-1",
                          rank_fn=_rank_ok, allowlist_fn=_allow)
    assert "hello techdata procurement" in draft.body.lower()  # not "hello sup-7"


# ── RFI: human-fired supplier clarification (consumes a needs_info send-gate) ──
def _to_awaiting_approval_with_supplier(db):
    cid = _committed_case(db)
    D.draft_and_record(db, case_id=cid, actor=AG(), item_ref="SKU-1", quantity=6,
                       rank_fn=_rank_ok, allowlist_fn=_allow, now_iso="2026-06-26 09:05:10")
    D.request_supplier_approval(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:05:20")
    return cid


def test_request_supplier_info_sends_claim_safe_rfi_and_advances(db):
    cid = _to_awaiting_approval_with_supplier(db)
    res, rfi = D.request_supplier_info(db, case_id=cid, actor=HU(),
                                       question="What is your lead time and MOQ for this quantity?",
                                       now_iso="2026-06-26 09:06:00")
    assert res.ok and wf.current_state(db, cid) == S.AWAITING_SUPPLIER_INFO
    assert "this request does not constitute a purchase order" in rfi["body"].lower()
    assert rfi["recipient_domain"] == "approved-supplier.example" and rfi["content_hash"]


def test_request_supplier_info_rejects_price_leak(db):
    cid = _to_awaiting_approval_with_supplier(db)
    res, rfi = D.request_supplier_info(db, case_id=cid, actor=HU(), question="We'll pay $900 each, ok?",
                                       now_iso="2026-06-26 09:06:00")
    assert res.ok is False and res.reason == "unsafe_rfi" and rfi is None
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL  # unchanged — unsafe RFI refused


def test_record_supplier_info_returns_to_approval_gate(db):
    cid = _to_awaiting_approval_with_supplier(db)
    D.request_supplier_info(db, case_id=cid, actor=HU(), question="Lead time?", now_iso="2026-06-26 09:06:00")
    res, resp = D.record_supplier_info(db, case_id=cid, actor=HU(), answer="7 days, MOQ 1.",
                                       now_iso="2026-06-26 09:10:00")
    assert res.ok and wf.current_state(db, cid) == S.AWAITING_APPROVAL
    assert resp == {"answer": "7 days, MOQ 1."}


# ── RFI actually transmits (transport seam) + inbound reply is EXTERNAL + trust-verified ──
class _FailTransport:
    def send(self, *, to, subject, body, idempotency_key=""):
        class _R:
            status = "failed"
            provider_ref = ""
            detail = "smtp_boom"
        return _R()


def test_request_supplier_info_records_transport_send(db):
    cid = _to_awaiting_approval_with_supplier(db)
    res, rfi = D.request_supplier_info(db, case_id=cid, actor=HU(), question="Lead time and MOQ?",
                                       now_iso="2026-06-26 09:06:00")
    assert res.ok and rfi["status"] == "sent" and rfi["provider_ref"].startswith("DEMO-OUT-")
    assert wf.current_state(db, cid) == S.AWAITING_SUPPLIER_INFO


def test_request_supplier_info_send_failure_keeps_state(db):
    cid = _to_awaiting_approval_with_supplier(db)
    res, rfi = D.request_supplier_info(db, case_id=cid, actor=HU(), question="Lead time?",
                                       transport=_FailTransport(), now_iso="2026-06-26 09:06:00")
    assert res.ok is False and res.reason == "rfi_send_failed" and rfi is None
    assert wf.current_state(db, cid) == S.AWAITING_APPROVAL  # no transmit → no transition


def test_receive_supplier_info_external_trusted_advances(db):
    from src.app.services.fulfillment import external_comms as EC
    cid = _to_awaiting_approval_with_supplier(db)
    D.request_supplier_info(db, case_id=cid, actor=HU(), question="Lead time?", now_iso="2026-06-26 09:06:00")
    res = EC.receive_supplier_info(db, case_id=cid, raw_body="Lead time 7 days, MOQ 1.",
                                   sender_domain="approved-supplier.example", provider_ref="IN-1",
                                   trusted_fn=lambda d: d == "approved-supplier.example",
                                   now_iso="2026-06-26 09:10:00")
    assert res.ok and wf.current_state(db, cid) == S.AWAITING_APPROVAL


def test_receive_supplier_info_untrusted_sender_rejected(db):
    from src.app.services.fulfillment import external_comms as EC
    cid = _to_awaiting_approval_with_supplier(db)
    D.request_supplier_info(db, case_id=cid, actor=HU(), question="Lead time?", now_iso="2026-06-26 09:06:00")
    res = EC.receive_supplier_info(db, case_id=cid, raw_body="evil", sender_domain="attacker.example",
                                   trusted_fn=lambda d: False, now_iso="2026-06-26 09:10:00")
    assert res.ok is False and res.reason == "untrusted_sender"
    assert wf.current_state(db, cid) == S.AWAITING_SUPPLIER_INFO  # no state change on untrusted inbound
