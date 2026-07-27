"""Step 4 — governed send/receive: stale-approval block, quarantine, strict parse, expiry hard-reject."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import external_comms as ec
from src.app.services.fulfillment import sandbox_supplier as sb
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

_DRAFT = {"content_hash": "H1", "recipient_domain": "approved-supplier.example", "supplier_ref": "SUP-7",
           "commercial_scope": {"item_ref": "SKU-1", "quantity": 6}}


def _to_approved(db):
    cid = wf.open_case(db, buyer_uid_hash="u1", source_trace_id="T1", requested_by="u1",
                       now_iso="2026-06-26 09:00:00"); db.commit()
    wf.transition(db, case_id=cid, event="availability_assessed", actor=AG(),
                  state_patch={"availability": {"shortfall": 6, "requested_qty": 10}}, now_iso="2026-06-26 09:00:01")
    wf.transition(db, case_id=cid, event="request_buyer_commitment", actor=AG(), now_iso="2026-06-26 09:00:02")
    wf.transition(db, case_id=cid, event="buyer_committed", actor=BU(), now_iso="2026-06-26 09:05:00")
    wf.transition(db, case_id=cid, event="external_message_drafted", actor=AG(),
                  state_patch={"draft": dict(_DRAFT)}, now_iso="2026-06-26 09:05:10")
    wf.transition(db, case_id=cid, event="approval_requested", actor=AG(), now_iso="2026-06-26 09:05:15")
    wf.transition(db, case_id=cid, event="approval_granted", actor=HU(), now_iso="2026-06-26 09:10:00")
    assert wf.current_state(db, cid) == S.APPROVED_TO_SEND
    return cid


def _to_sent(db):
    cid = _to_approved(db)
    assert ec.send_approved(db, case_id=cid, actor=HU(), approval_content_hash="H1",
                            now_iso="2026-06-26 09:10:05").ok
    return cid


# ── send (hash-checked) ──────────────────────────────────────────────────────
def test_send_with_matching_hash_sends(db):
    cid = _to_approved(db)
    r = ec.send_approved(db, case_id=cid, actor=HU(), approval_content_hash="H1", now_iso="2026-06-26 09:10:05")
    assert r.ok and wf.current_state(db, cid) == S.QUOTE_SENT


def test_send_through_reliable_queue_when_flag_on(db, monkeypatch):
    """GATE-2 reliable path: with FULFILLMENT_OUTBOUND_QUEUE_ENABLED the send routes through the durable queue —
    it still advances to QUOTE_SENT, AND a durable 'sent' outbound_message row exists for retry/ack tracking."""
    monkeypatch.setenv("FULFILLMENT_OUTBOUND_QUEUE_ENABLED", "1")
    from sqlalchemy import text
    cid = _to_approved(db)
    r = ec.send_approved(db, case_id=cid, actor=HU(), approval_content_hash="H1", now_iso="2026-06-26 09:10:05")
    assert r.ok and wf.current_state(db, cid) == S.QUOTE_SENT
    row = db.execute(text("SELECT status, idempotency_key, actor_type, transition_event "
                          "FROM outbound_message WHERE case_id=:c"), {"c": cid}).fetchone()
    assert row is not None and row[0] == "sent" and row[1] == "H1"
    assert row[2] == "human_operator" and row[3] == "external_message_sent"


def test_send_with_stale_approval_is_blocked(db):
    cid = _to_approved(db)
    # the approval was for hash H1 but the current draft is H1 — simulate an approval that no longer matches
    r = ec.send_approved(db, case_id=cid, actor=HU(), approval_content_hash="H2-OLD", now_iso="2026-06-26 09:10:05")
    assert r.ok is False and r.reason == "stale_approval" and r.http_status == 409
    assert wf.current_state(db, cid) == S.APPROVED_TO_SEND  # NOT sent


# ── receive (correlate + quarantine) ─────────────────────────────────────────
def test_trusted_reply_is_received(db):
    cid = _to_sent(db)
    reply = sb.generate_reply(case_ref=cid, scenario="full_quote", requested_qty=6)
    r = ec.receive_reply(db, case_id=cid, raw_body=reply["body"], sender_domain=reply["sender_domain"],
                         provider_ref=reply["provider_ref"], trusted_fn=lambda d: d == sb.TRUSTED_DOMAIN,
                         now_iso="2026-06-26 09:26:00")
    assert r.ok and wf.current_state(db, cid) == S.QUOTE_RECEIVED


def test_untrusted_sender_is_quarantined(db):
    cid = _to_sent(db)
    reply = sb.generate_reply(case_ref=cid, scenario="untrusted_sender", requested_qty=6)
    r = ec.receive_reply(db, case_id=cid, raw_body=reply["body"], sender_domain=reply["sender_domain"],
                         trusted_fn=lambda d: d == sb.TRUSTED_DOMAIN, now_iso="2026-06-26 09:26:00")
    assert r.ok and wf.current_state(db, cid) == S.SUPPLIER_RESPONSE_QUARANTINED


# ── receive security boundary ────────────────────────────────────────────────
def test_compromised_trusted_supplier_email_is_quarantined_before_quote_receive(db):
    cid = _to_sent(db)
    verdict = {
        "severity": "critical",
        "route": "security_review",
        "verdict_action": "security_review",
        "reasons": ["attachment_active_content", "oob_verification_required"],
        "tags": ["email_security", "bec", "ioc:url"],
        "evidence_snapshot": {
            "hard_security_triggered": True,
            "ingest_gate": {"blocked": True},
        },
    }
    r = ec.receive_email_reply(
        db,
        case_id=cid,
        email={
            "from_addr": "quotes@approved-supplier.example",
            "subject": "Updated quote and payment details",
            "body": "6 units at AUD 1115 each. Use the attached new bank details.",
            "attachments": [{"name": "Wire_Transfer_Authorization_Form.pdf"}],
        },
        sender_domain="approved-supplier.example",
        trusted_fn=lambda _: True,
        security_evaluator=lambda *_args, **_kwargs: verdict,
    )
    assert r.ok and wf.current_state(db, cid) == S.SUPPLIER_RESPONSE_QUARANTINED
    cur = wf.repository.current_version(db, cid, "default")
    assert "inbound" not in cur.state_json
    assert cur.state_json["quarantine"]["reason"] == "inbound_security_review"
    assert cur.state_json["quarantine"]["security"]["severity"] == "critical"


def test_clean_authenticated_supplier_email_can_reach_quote_receive(db):
    cid = _to_sent(db)
    verdict = {
        "severity": "warning",
        "route": "human_review",
        "verdict_action": "quarantine",
        "reasons": ["multi-signal threshold met", "ml_gate_review"],
        "tags": ["email_security"],
        "evidence_snapshot": {"hard_security_triggered": False},
    }
    r = ec.receive_email_reply(
        db,
        case_id=cid,
        email={
            "from_addr": "quotes@approved-supplier.example",
            "reply_to": "quotes@approved-supplier.example",
            "subject": "RFQ response",
            "body": "Quantity 6 units. AUD 1115 per unit. Lead time 5 days.",
            "attachments": [],
            "spf_result": "pass",
            "dkim_result": "pass",
            "dmarc_result": "pass",
        },
        sender_domain="approved-supplier.example",
        trusted_fn=lambda _: True,
        security_evaluator=lambda *_args, **_kwargs: verdict,
    )
    assert r.ok and wf.current_state(db, cid) == S.QUOTE_RECEIVED


# ── parse (strict schema + evidence spans) ───────────────────────────────────
def test_parse_full_quote_extracts_fields_with_spans():
    reply = sb.generate_reply(case_ref="FC-1", scenario="full_quote", requested_qty=6, unit_amount_cents=111500)
    pq = ec.parse_quote(reply["body"], {"quantity": 6})
    assert pq["quoted_quantity"] == 6 and pq["unit_amount_cents"] == 111500
    assert pq["dispatch_ready_at"] == "2026-07-03" and pq["quote_expires_at"] == "2026-07-15"
    assert pq["confidence"] >= 0.9 and not pq["contradictory"]
    fields = {s["field"] for s in pq["evidence_spans"]}
    assert {"quoted_quantity", "unit_amount", "dispatch_ready_at", "quote_expires_at"} <= fields


def test_parse_explicit_landed_unit_cost_with_evidence():
    body = (
        "Quantity: 6\nUnit price: AUD 1,115 per unit\n"
        "Landed unit cost: AUD 1,245.50\nDispatch by 3 July 2026\nValid until 15 July 2026"
    )
    pq = ec.parse_quote(body, {"quantity": 6})
    assert pq["unit_amount_cents"] == 111500
    assert pq["landed_unit_cost_cents"] == 124550
    assert pq["landed_cost_currency"] == "AUD"
    assert "landed_unit_cost" in {span["field"] for span in pq["evidence_spans"]}


def test_parse_does_not_treat_ordinary_unit_quote_as_landed_cost():
    pq = ec.parse_quote("Quantity: 6\nUnit price: AUD 1,115 per unit", {"quantity": 6})
    assert pq["unit_amount_cents"] == 111500
    assert pq["landed_unit_cost_cents"] is None
    assert pq["landed_cost_currency"] is None


def test_parse_contradictory_quantity_lowers_confidence():
    reply = sb.generate_reply(case_ref="FC-1", scenario="contradictory_quantity", requested_qty=6)
    pq = ec.parse_quote(reply["body"], {"quantity": 6})
    assert pq["contradictory"] is True and pq["confidence"] < 0.9


def test_record_parsed_stores_quote(db):
    cid = _to_sent(db)
    reply = sb.generate_reply(case_ref=cid, scenario="full_quote", requested_qty=6)
    ec.receive_reply(db, case_id=cid, raw_body=reply["body"], sender_domain=reply["sender_domain"],
                     trusted_fn=lambda d: True, now_iso="2026-06-26 09:26:00")
    r = ec.record_parsed(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:26:10")
    assert r.ok and wf.current_state(db, cid) == S.QUOTE_RECEIVED
    cur = wf.repository.current_version(db, cid)
    assert cur.state_json["parsed_quote"]["quoted_quantity"] == 6


# ── validate (human; expired hard-reject) ────────────────────────────────────
def test_validate_unexpired_quote_advances(db):
    cid = _to_sent(db)
    reply = sb.generate_reply(case_ref=cid, scenario="full_quote", requested_qty=6)
    ec.receive_reply(db, case_id=cid, raw_body=reply["body"], sender_domain=reply["sender_domain"],
                     trusted_fn=lambda d: True, now_iso="2026-06-26 09:26:00")
    ec.record_parsed(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:26:10")
    r = ec.validate_quote(db, case_id=cid, actor=HU(), today="2026-06-27", now_iso="2026-06-27 09:00:00")
    assert r.ok and wf.current_state(db, cid) == S.QUOTE_VALIDATED
    assert wf.repository.current_version(db, cid).state_json["validated_quote"]["validation"]["in_scope"] is True


def test_validate_explicit_landed_quote_materializes_authoritative_supplier_offer(db):
    from src.app.services.supplier_catalog import best_supplier_cost, ensure_tables

    ensure_tables(db)
    cid = _to_sent(db)
    raw = (
        "Quantity: 6\nUnit price: AUD 1,115 per unit\n"
        "Landed unit cost: AUD 1,245.50\nDispatch by 3 July 2026\nValid until 15 August 2026"
    )
    ec.receive_reply(db, case_id=cid, raw_body=raw, sender_domain="approved-supplier.example",
                     provider_ref="QUOTE-AUTH-1", trusted_fn=lambda d: True,
                     now_iso="2026-06-26 09:26:00")
    ec.record_parsed(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:26:10")

    result = ec.validate_quote(db, case_id=cid, actor=HU(), today="2026-06-27",
                               now_iso="2026-06-27T09:00:00+00:00", tenant_id="default")

    assert result.ok
    offer = best_supplier_cost(db, "SKU-1", tenant_id="default", currency="AUD")
    assert offer is not None
    assert offer["supplier_id"] == "SUP-7"
    assert offer["purchase_unit_cost_cents"] == 111500
    assert offer["unit_cost_cents"] == 124550
    assert offer["simulation_only"] is False
    assert offer["cost_kind"] == "validated_landed_quote"
    assert offer["source_record_id"] == "QUOTE-AUTH-1"


def test_validate_ordinary_unit_quote_does_not_create_authoritative_offer(db):
    from src.app.services.supplier_catalog import ensure_tables

    ensure_tables(db)
    cid = _to_sent(db)
    reply = sb.generate_reply(case_ref=cid, scenario="full_quote", requested_qty=6)
    ec.receive_reply(db, case_id=cid, raw_body=reply["body"], sender_domain=reply["sender_domain"],
                     provider_ref=reply["provider_ref"], trusted_fn=lambda d: True,
                     now_iso="2026-06-26 09:26:00")
    ec.record_parsed(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:26:10")

    result = ec.validate_quote(db, case_id=cid, actor=HU(), today="2026-06-27",
                               now_iso="2026-06-27T09:00:00+00:00")

    assert result.ok
    count = db.execute(text("SELECT COUNT(*) FROM supplier_offer WHERE simulation_only=0")).scalar()
    assert count == 0


def test_validate_expired_quote_is_hard_rejected(db):
    cid = _to_sent(db)
    reply = sb.generate_reply(case_ref=cid, scenario="expired_quote", requested_qty=6)  # valid until 2026-06-20
    ec.receive_reply(db, case_id=cid, raw_body=reply["body"], sender_domain=reply["sender_domain"],
                     trusted_fn=lambda d: True, now_iso="2026-06-26 09:26:00")
    ec.record_parsed(db, case_id=cid, actor=AG(), now_iso="2026-06-26 09:26:10")
    # even though a human is validating, an expired quote routes to quote_expired
    r = ec.validate_quote(db, case_id=cid, actor=HU(), today="2026-06-27", now_iso="2026-06-27 09:00:00")
    assert r.ok and wf.current_state(db, cid) == S.QUOTE_EXPIRED
