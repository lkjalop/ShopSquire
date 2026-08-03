"""External-party communication boundary (agnostic CORE) — send/receive/parse/validate, governed.

Each function fires exactly one workflow transition, so the domain guards + bitemporal audit apply:
  • send_approved        — HUMAN fires external_message_sent, but ONLY after the approval's content_hash
                           still matches the current draft (an edit after approval → stale_approval, no
                           send). Stages the outbound in the sandbox (no real transport here).
  • receive_reply        — correlates an inbound reply to its case + verifies the sender domain; an
                           untrusted/mismatched sender is QUARANTINED, never parsed.
  • parse_quote          — strict-schema deterministic parse with EVIDENCE SPANS + a confidence; a
                           contradictory quantity lowers confidence. The raw body stays authoritative;
                           parsed output NEVER auto-creates a PO.
  • record_parsed        — AGENT fires supplier_response_parsed (or quote_parse_failed on no signal).
  • validate_quote       — HUMAN fires supplier_quote_validated, but an EXPIRED quote is hard-rejected
                           to quote_expired regardless.

Vertical-blind; best-effort; never raises into a caller.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from src.app.services.fulfillment import workflow
from src.app.services.fulfillment.domain import Actor, ActorType

_log = logging.getLogger("shopsquire.fulfillment.external_comms")


def _outbound_queue_enabled() -> bool:
    """Route the GATE-2 send through the durable outbound queue (retry/backoff/dead-letter/855-ack). OFF by
    default — the direct-transport path stays byte-identical to the prior behaviour."""
    return str(os.getenv("FULFILLMENT_OUTBOUND_QUEUE_ENABLED", "0")).strip().lower() in {"1", "true", "yes", "on"}

# Robust supplier-quote extraction. The patterns are GENERIC commercial parsing (units / money / dates /
# lead time) — vertical-blind, no product flavour. The RAW body stays authoritative and ambiguous input is
# left as None (never invented), so broadening only RECOVERS more real-world formats; it never fabricates.

# quantity: "6 units" / "6 pcs" / "6 pieces" / "qty: 6" / "quantity of 6" (thousands separators allowed)
_QTY_RE = re.compile(
    r"(?:\bqty|\bquantity)\b\s*(?:of\s+|:\s*)?(?P<a>\d[\d,]*)\b"
    r"|\b(?P<b>\d[\d,]*)\s*(?:units?|pcs?|pieces?)\b",
    re.IGNORECASE)

# unit price with currency: "$1115" / "$1,115.00" / "€1234" / "1115 USD" / "USD 1,115.00"
_PRICE_RE = re.compile(
    r"(?P<sym>[$€£¥])\s?(?P<amt1>\d[\d,]*(?:\.\d{1,2})?)"
    r"|(?P<amt2>\d[\d,]*(?:\.\d{1,2})?)\s?(?P<code1>USD|AUD|EUR|GBP|JPY|NZD|CAD)\b"
    r"|\b(?P<code2>USD|AUD|EUR|GBP|JPY|NZD|CAD)\s?(?P<amt3>\d[\d,]*(?:\.\d{1,2})?)",
    re.IGNORECASE)
# "per unit" / "/unit" / "each" / "/ea" — prefer a price in this context (a unit price, not a line total)
_PER_UNIT_RE = re.compile(r"\b(?:per\s+unit|each|/\s*unit|/\s*ea|ea\b|pp\b)", re.IGNORECASE)

# Only an explicitly labelled landed unit cost can unlock margin headroom. A normal
# quoted unit price is not landed COGS because freight, duty and handling may be absent.
_LANDED_UNIT_RE = re.compile(
    r"\blanded\s+(?:unit\s+)?(?:cost|price)\b(?:\s+per\s+unit)?\s*(?::|is|of)?\s*"
    r"(?:\$(?P<dollar>\d[\d,]*(?:\.\d{1,2})?)"
    r"|(?P<code1>USD|AUD|EUR|GBP|JPY|NZD|CAD)\s*(?P<amount1>\d[\d,]*(?:\.\d{1,2})?)"
    r"|(?P<amount2>\d[\d,]*(?:\.\d{1,2})?)\s*(?P<code2>USD|AUD|EUR|GBP|JPY|NZD|CAD)\b)",
    re.IGNORECASE,
)

# lead time in days: "lead time 10 days" / "ships in 10 business days" / "10 day lead"
_LEAD_RE = re.compile(
    r"(?:lead[\s-]?time|ships?\s+in|dispatch(?:es)?\s+in|delivery\s+in)\D{0,10}?(?P<a>\d+)\s*(?:business\s+)?days?\b"
    r"|\b(?P<b>\d+)[\s-]*(?:business\s+)?day\s+lead\b",
    re.IGNORECASE)

# a date token in ISO, "3 July 2026", "3 Jul 2026", or "July 3, 2026"
_DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
_DISPATCH_RE = re.compile(r"(?:dispatch(?:ed)?|ready\s+to\s+dispatch|ready|ship(?:ping)?)\b(?:\s+(?:on|by))?\s+(" + _DATE + r")", re.IGNORECASE)
_DELIVERY_RE = re.compile(r"(?:estimated\s+delivery|delivery|deliver|eta)\b(?:\s+(?:on|by))?\s+(" + _DATE + r")", re.IGNORECASE)
_EXPIRY_RE = re.compile(r"(?:valid\s+until|valid\s+till|valid\s+to|expires?(?:\s+on)?|quote\s+valid\s+until)\s+(" + _DATE + r")", re.IGNORECASE)
_SUBSTITUTE_RE = re.compile(r"substitute", re.IGNORECASE)

_CURRENCY_SYMBOL = {"$": "AUD", "€": "EUR", "£": "GBP", "¥": "JPY"}  # bare $ → the platform default (AUD)
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _to_cents(amount: str) -> Optional[int]:
    try:
        return int(round(float(str(amount).replace(",", "")) * 100))
    except (TypeError, ValueError):
        return None


def _normalize_date(raw: str) -> Optional[str]:
    """Normalise a captured date token to ISO (YYYY-MM-DD), or None if unparseable. Numeric DD/MM vs MM/DD
    is deliberately NOT guessed (a wrong date is worse than none) — only ISO + named-month forms convert."""
    s = (raw or "").strip().rstrip(".").replace(",", "")
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return s
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", s)        # 3 July 2026
    if m:
        day, mon, year = int(m.group(1)), _MONTHS.get(m.group(2)[:3].lower()), int(m.group(3))
        if mon and 1 <= day <= 31:
            return f"{year:04d}-{mon:02d}-{day:02d}"
    m = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{1,2})\s+(\d{4})", s)        # July 3 2026
    if m:
        mon, day, year = _MONTHS.get(m.group(1)[:3].lower()), int(m.group(2)), int(m.group(3))
        if mon and 1 <= day <= 31:
            return f"{year:04d}-{mon:02d}-{day:02d}"
    return None


def _default_trusted(domain: str) -> bool:
    try:
        from src.app.services.supplier_domain_guard import is_trusted_supplier_domain
        return bool(is_trusted_supplier_domain(domain))
    except Exception:
        return False


# ── send (human, hash-checked) ────────────────────────────────────────────────
def _transmit_current_draft(db, *, case_id: str, cur, draft: Dict[str, Any], actor: Actor, event: str,
                            reason_code: str, transport: Optional[Any], tenant_id: str,
                            now_iso: Optional[str], trace_id: Optional[str]) -> workflow.TransitionResult:
    """Shared transport + record for BOTH the human (external_message_sent) and the autonomous
    (external_message_sent_autonomous) send. Sends via the transport seam (SANDBOX by default; SMTP at
    deploy); a REAL transport failure returns send_failed and records NO send (the case stays
    APPROVED_TO_SEND so it can be retried). The caller has already verified the draft is current."""
    from src.app.services.fulfillment.transport import get_transport
    tx = transport or get_transport()
    recipient = str(draft.get("recipient_email") or draft.get("recipient_domain") or "")
    subject = str(draft.get("subject") or "")
    body = str(draft.get("body") or "")
    content_hash = str(draft.get("content_hash") or "")
    artifact_ids = [str(value) for value in (draft.get("artifact_ids") or []) if str(value).strip()]
    artifact_binding_ids: List[str] = []
    if artifact_ids:
        try:
            from src.app.security.artifact_authority import bind_decision, evaluate_bound_artifacts

            artifact_result = evaluate_bound_artifacts(
                db, tenant_id=tenant_id, artifact_ids=artifact_ids,
            )
            if not artifact_result.allowed:
                return workflow.TransitionResult(
                    False, case_id, cur.state, "artifact_authority_blocked", http_status=409,
                )
            for artifact_id in artifact_ids:
                binding = bind_decision(
                    db,
                    tenant_id=tenant_id,
                    artifact_id=artifact_id,
                    decision_kind="supplier_message",
                    decision_id=content_hash,
                )
                artifact_binding_ids.append(str(binding["id"]))
            if artifact_binding_ids:
                from sqlalchemy import text as _sql_text
                db.execute(
                    _sql_text(
                        "UPDATE artifact_decision_bindings SET status='queued' "
                        "WHERE tenant_id=:tenant_id AND id IN ("
                        + ",".join(f":binding_{idx}" for idx in range(len(artifact_binding_ids)))
                        + ")"
                    ),
                    {
                        "tenant_id": tenant_id,
                        **{f"binding_{idx}": value for idx, value in enumerate(artifact_binding_ids)},
                    },
                )
        except Exception as exc:
            _log.error("artifact authority unavailable for outbound %s: %s", case_id, repr(exc)[:160])
            return workflow.TransitionResult(
                False, case_id, cur.state, "artifact_authority_unavailable", http_status=503,
            )
    transport_detail = ""
    party_ref = None
    # This transport seam sends email.  A supplier's authoritative preferred
    # channel must not be silently flattened into email: phone/portal become
    # human tasks, while EDI/cXML/API require their dedicated connector.
    channel_plan = draft.get("channel_plan") if isinstance(draft.get("channel_plan"), dict) else {}
    channel = str(channel_plan.get("channel") or "email").strip().lower()
    response_expectation = (
        channel_plan.get("response_expectation")
        or draft.get("supplier_response_expectation")
        or (cur.state_json.get("supplier_response_expectation") if cur else None)
        or {}
    )
    if channel == "phone":
        # A phone preference is a durable operator task, never an excuse to flatten
        # the contact into email and never a transport failure that disappears.
        from src.app.services.fulfillment import outbound_queue as _oq
        queued = _oq.enqueue(
            db, case_id=case_id, recipient=recipient, subject=subject, body=body,
            idempotency_key=content_hash, tenant_id=tenant_id,
            actor_type=getattr(actor.type, "value", str(actor.type)), actor_id=actor.id,
            transition_event=event, now_iso=now_iso, party_ref=party_ref,
            channel=channel, response_expectation=response_expectation,
        )
        if queued.get("message_id"):
            try:
                from src.app.services.procurement_human_room import request_room
                request_room(
                    db, tenant_id=tenant_id, case_id=case_id, actor_id=actor.id,
                    idempotency_key=f"phone-contact:{content_hash}", now_iso=now_iso,
                )
            except Exception:
                pass  # migration-first; the durable phone queue remains authoritative.
        return workflow.TransitionResult(
            False, case_id, cur.state,
            "supplier_phone_contact_queued" if queued.get("message_id") else "supplier_phone_queue_failed",
            http_status=202 if queued.get("message_id") else 503,
        )
    if channel == "portal":
        return workflow.TransitionResult(
            False, case_id, cur.state, "supplier_portal_human_task_required", http_status=409,
        )
    if channel in {"edi", "cxml", "api"}:
        return workflow.TransitionResult(
            False, case_id, cur.state, f"supplier_{channel}_connector_required", http_status=409,
        )
    try:
        from src.app.services.communication_party_binding import (
            bind_authoritative_party,
        )
        binding = bind_authoritative_party(
            db,
            tenant_id=tenant_id,
            party_type="supplier",
            source="supplier_registry",
            object_type="approved_supplier",
            external_id=str(draft.get("recipient_ref") or ""),
            authority="approved_supplier_registry",
            provenance_ref=f"case:{case_id}|draft:{content_hash}",
            display_name=str(draft.get("recipient_ref") or recipient),
        )
        party_ref = str(binding["party_id"])
    except Exception as exc:
        _log.warning("supplier Party binding unavailable for %s: %s", case_id, exc)
        if str(os.getenv("APP_ENV") or "").strip().lower() in {
            "prod", "production", "staging",
        }:
            return workflow.TransitionResult(
                False,
                case_id,
                cur.state,
                "authoritative_party_binding_required",
                http_status=503,
            )

    # OUTBOUND INTEGRITY GATE — the single chokepoint for BOTH human and autonomous send. Destination
    # allowlisting + GATE-2 already stop the WRONG place; this stops the WRONG CONTENT — the platform
    # must never RELAY a poisoned payload (injected instructions, exfil/C2, links) or LEAK a secret to a
    # supplier and become a threat vector itself. block → do not transmit, hold for review; the finding
    # is TRACED (keyed to the case) so bounded-autonomy safety is visible on the Procurement tab.
    try:
        from src.app.services.fulfillment.outbound_integrity import scan_outbound_supplier_message
        _integrity = scan_outbound_supplier_message(subject, body, recipient=recipient)
    except Exception as _scan_exc:
        # D6 FAIL-CLOSED: if the outbound content scanner can't run, we CANNOT prove the message is
        # safe to relay to a supplier — hold for review, never default to allow (the old fail-OPEN
        # let an unscanned/poisoned payload transmit on any scanner error).
        _log.error("outbound integrity scan FAILED — holding for review (fail-closed): %s",
                   repr(_scan_exc)[:120])
        _integrity = {"action": "review", "findings": ["scan_unavailable"], "categories": []}
    if _integrity.get("action") in ("block", "review"):
        try:
            from src.app.services.decision_log import log_trace_event as _lte
            _lte(trace_id=(trace_id or f"case:{case_id}"), event_type="outbound_integrity_block",
                 source_type="agent", source_id="Outbound_Integrity_Guard", target_type="supplier_message",
                 target_id=case_id, payload={
                     "action": _integrity.get("action"), "findings": _integrity.get("findings"),
                     "categories": _integrity.get("categories"),
                     "recipient_domain": (recipient.split("@", 1)[1].lower() if "@" in recipient else recipient),
                     "note": "drafted supplier message quarantined before send — platform did not relay it"})
        except Exception as _trace_exc:
            import logging as _l
            _l.getLogger("shopsquire.fulfillment").debug("integrity trace emit failed: %s", _trace_exc)
        _rc = "blocked_content" if _integrity.get("action") == "block" else "held_for_content_review"
        return workflow.TransitionResult(False, case_id, cur.state, _rc, http_status=422)
    if _outbound_queue_enabled():
        # RELIABLE path: durably enqueue (idempotent on content_hash) + attempt once. A transient failure
        # leaves the message PENDING for the background processor to retry — the human can re-dispatch (deduped,
        # never double-sends). Only a confirmed 'sent' advances the state machine, so the human-only invariant holds.
        from src.app.services.fulfillment import outbound_queue as _oq
        r = _oq.send_now(db, case_id=case_id, recipient=recipient, subject=subject, body=body,
                         idempotency_key=content_hash, transport=tx, tenant_id=tenant_id,
                         actor_type=getattr(actor.type, "value", str(actor.type)), actor_id=actor.id,
                         transition_event=event, now_iso=now_iso,
                         channel=channel, response_expectation=response_expectation,
                         party_ref=party_ref,
                         grounding_materials=[
                             {
                                 "grounding_type": "fact",
                                 "source_ref": evidence.get("evidence_id"),
                                 "source_version": evidence.get("source_version") or "1",
                                 "content": evidence.get("summary"),
                             }
                             for evidence in (draft.get("evidence") or [])
                             if isinstance(evidence, dict)
                             and evidence.get("evidence_id")
                             and evidence.get("summary")
                         ])
        if r.get("status") != "sent":
            return workflow.TransitionResult(False, case_id, cur.state, "send_failed", http_status=502)
        provider_ref = r.get("provider_ref", "")
        transport_detail = r.get("detail", "") or "queued"
    else:
        sent = tx.send(to=recipient, subject=subject, body=body, idempotency_key=content_hash)
        if getattr(sent, "status", "failed") != "sent":
            return workflow.TransitionResult(False, case_id, cur.state, "send_failed", http_status=502)
        provider_ref = sent.provider_ref
        transport_detail = getattr(sent, "detail", "")
    transition_result = workflow.transition(
        db, case_id=case_id, event=event, actor=actor, reason_code=reason_code,
        evidence={"content_hash": draft.get("content_hash"), "provider_ref": provider_ref,
                  "recipient": recipient, "recipient_domain": draft.get("recipient_domain"),
                  "transport": transport_detail},
        state_patch={"outbound": {"provider_ref": provider_ref, "recipient_domain": draft.get("recipient_domain"),
                                  "recipient": recipient, "content_hash": draft.get("content_hash"), "status": "sent",
                                  "transport": transport_detail}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    if transition_result.ok and provider_ref:
        if artifact_binding_ids:
            try:
                from sqlalchemy import text as _sql_text
                db.execute(
                    _sql_text(
                        "UPDATE artifact_decision_bindings SET status='executed' "
                        "WHERE tenant_id=:tenant_id AND decision_kind='supplier_message' "
                        "AND decision_id=:decision_id"
                    ),
                    {"tenant_id": tenant_id, "decision_id": content_hash},
                )
            except Exception as exc:
                _log.error("artifact binding execution mark failed for %s: %s", case_id, repr(exc)[:160])
        try:
            from src.app.services.email_thread_correlation import record_outbound_reference

            record_outbound_reference(
                db,
                tenant_id=tenant_id,
                provider="supplier_transport",
                provider_message_id=provider_ref,
                case_id=case_id,
            )
        except Exception as exc:
            _log.warning("outbound email correlation record unavailable: %s", repr(exc)[:160])
    return transition_result


def send_approved(db, *, case_id: str, actor: Actor, approval_content_hash: Optional[str],
                  transport: Optional[Any] = None, tenant_id: str = "default", now_iso: Optional[str] = None,
                  trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """HUMAN fires external_message_sent — but only if the approval still matches the current draft. The
    actual transmission goes through the transport seam (SANDBOX by default; SMTP at deploy). A REAL
    transport failure returns send_failed and records NO send (the human can retry)."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    draft = (cur.state_json.get("draft") if cur else None) or {}
    if not draft.get("content_hash"):
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "no_draft", http_status=409)
    if approval_content_hash != draft.get("content_hash"):
        # the draft was edited after approval → the approval is void; do NOT send.
        return workflow.TransitionResult(False, case_id, cur.state, "stale_approval", http_status=409)
    return _transmit_current_draft(db, case_id=case_id, cur=cur, draft=draft, actor=actor,
                                   event="external_message_sent", reason_code="human_approved_send",
                                   transport=transport, tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)


def send_autonomous(db, *, case_id: str, actor: Actor, transport: Optional[Any] = None,
                    tenant_id: str = "default", now_iso: Optional[str] = None,
                    trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """WS-C: AGENT fires external_message_sent_autonomous after autonomous_send's guards + the action-gate
    approval. No stale-approval check is needed (the gate just authorized THIS exact draft in the same
    call); the content_hash is still pinned on the outbound for the audit trail."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    draft = (cur.state_json.get("draft") if cur else None) or {}
    if not draft.get("content_hash"):
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "no_draft", http_status=409)
    return _transmit_current_draft(db, case_id=case_id, cur=cur, draft=draft, actor=actor,
                                   event="external_message_sent_autonomous", reason_code="autonomous_rfq_send",
                                   transport=transport, tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)


# ── receive (correlate + verify, else quarantine) ─────────────────────────────
def _inbound_security_requires_quarantine(verdict: Dict[str, Any]) -> bool:
    """Interpret the email-security contract without treating generic ML review noise as malware."""
    severity = str(verdict.get("severity") or "").strip().lower()
    route = str(verdict.get("route") or "").strip().lower()
    tags = {str(tag or "").strip().lower() for tag in (verdict.get("tags") or [])}
    evidence = dict(verdict.get("evidence_snapshot") or {})
    ingest = dict(evidence.get("ingest_gate") or evidence.get("attachment_ingest_gate") or {})
    return bool(
        severity in {"high", "critical", "error"}
        or route in {"security_review", "block", "block_and_escalate"}
        or bool(evidence.get("hard_security_triggered"))
        or bool(evidence.get("oob_verification_required"))
        or bool(ingest.get("blocked"))
        or bool(tags.intersection({"bec", "supply_chain", "prompt_injection", "malware"}))
    )


def receive_email_reply(
    db,
    *,
    case_id: str,
    email: Dict[str, Any],
    sender_domain: str,
    provider_ref: Optional[str] = None,
    raw_evidence_ref: Optional[str] = None,
    inbox_id: Optional[str] = None,
    tenant_id: str = "default",
    now_iso: Optional[str] = None,
    trace_id: Optional[str] = None,
    trusted_fn=None,
    security_evaluator=None,
) -> workflow.TransitionResult:
    """Security-screen a complete supplier email before it can enter quote parsing."""
    payload = dict(email or {})
    payload.setdefault("from_addr", f"quotes@{sender_domain}")
    payload.setdefault("reply_to", payload.get("from_addr"))
    payload.setdefault("body", "")
    payload.setdefault("attachments", [])
    payload.setdefault("external_sender", True)
    try:
        if security_evaluator is None:
            from src.app.security.email_security import evaluate_email_security
            security_evaluator = evaluate_email_security
        verdict = dict(security_evaluator(payload, tenant_id=tenant_id) or {})
    except Exception as exc:
        _log.error("supplier inbound security scan failed closed: %s", repr(exc)[:160])
        verdict = {
            "severity": "error",
            "route": "security_review",
            "reasons": ["security_scan_unavailable"],
            "tags": ["email_security"],
            "evidence_snapshot": {"hard_security_triggered": True},
        }

    if _inbound_security_requires_quarantine(verdict):
        summary = {
            "severity": str(verdict.get("severity") or "unknown"),
            "route": str(verdict.get("route") or "unknown"),
            "reasons": [str(x)[:120] for x in (verdict.get("reasons") or [])[:12]],
            "tags": [str(x)[:80] for x in (verdict.get("tags") or [])[:12]],
        }
        return workflow.transition(
            db,
            case_id=case_id,
            event="supplier_response_quarantined",
            actor=Actor(ActorType.SYSTEM, "email_security"),
            reason_code="inbound_security_review",
            evidence={
                "sender_domain": sender_domain,
                "provider_ref": provider_ref,
                "raw_evidence_ref": raw_evidence_ref,
                "inbox_id": inbox_id,
                "security": summary,
            },
            state_patch={
                "quarantine": {
                    "sender_domain": sender_domain,
                    "reason": "inbound_security_review",
                    "raw_evidence_ref": raw_evidence_ref,
                    "inbox_id": inbox_id,
                    "security": summary,
                }
            },
            tenant_id=tenant_id,
            now_iso=now_iso,
            trace_id=trace_id,
        )

    return receive_reply(
        db,
        case_id=case_id,
        raw_body=str(payload.get("body") or ""),
        sender_domain=sender_domain,
        provider_ref=provider_ref,
        tenant_id=tenant_id,
        now_iso=now_iso,
        trace_id=trace_id,
        trusted_fn=trusted_fn,
    )


def receive_reply(db, *, case_id: str, raw_body: str, sender_domain: str, provider_ref: Optional[str] = None,
                  tenant_id: str = "default", now_iso: Optional[str] = None, trace_id: Optional[str] = None,
                  trusted_fn=None) -> workflow.TransitionResult:
    """Correlate an inbound reply to its case and verify the sender. Untrusted → quarantine. A reply to a
    SUPERSEDED RFQ (the buyer amended / the operator retired it) is quarantined too — we never process a
    quote for an order that no longer stands (the post-send supersession safety: bug "supplier replies to a
    superseded RFQ")."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    if cur and cur.state == "SUPERSEDED":
        return workflow.TransitionResult(False, case_id, "SUPERSEDED", "superseded_rfq", http_status=409)
    trusted = (trusted_fn or _default_trusted)(sender_domain)
    if not trusted:
        return workflow.transition(
            db, case_id=case_id, event="supplier_response_quarantined", actor=Actor(ActorType.SYSTEM, "mailbox"),
            reason_code="untrusted_sender",
            evidence={"sender_domain": sender_domain, "provider_ref": provider_ref},
            state_patch={"quarantine": {"sender_domain": sender_domain, "reason": "untrusted_sender"}},
            tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    return workflow.transition(
        db, case_id=case_id, event="external_message_received", actor=Actor(ActorType.EXTERNAL, sender_domain),
        reason_code="correlated_inbound",
        evidence={"sender_domain": sender_domain, "provider_ref": provider_ref},
        state_patch={"inbound": {"sender_domain": sender_domain, "provider_ref": provider_ref,
                                 "raw_body": raw_body, "status": "received"}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)


# ── RFI inbound (supplier's clarification reply, EXTERNAL + trust-verified) ───
def receive_supplier_info(db, *, case_id: str, raw_body: str, sender_domain: str,
                          provider_ref: Optional[str] = None, tenant_id: str = "default",
                          now_iso: Optional[str] = None, trace_id: Optional[str] = None,
                          trusted_fn=None) -> workflow.TransitionResult:
    """Inbound RFI reply from the supplier: verify the sender is on the trusted allowlist, then fire
    supplier_info_received as an EXTERNAL actor (AWAITING_SUPPLIER_INFO → AWAITING_APPROVAL). An untrusted
    sender is REJECTED with no state change (the operator can investigate) — symmetry with receive_reply's
    quarantine on the RFQ path. This is the real inbound path; the operator-recorded record_supplier_info
    is the manual fallback."""
    trusted = (trusted_fn or _default_trusted)(sender_domain)
    if not trusted:
        cur = workflow.repository.current_version(db, case_id, tenant_id)
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "untrusted_sender",
                                         http_status=409)
    ans = str(raw_body or "").strip()
    return workflow.transition(
        db, case_id=case_id, event="supplier_info_received", actor=Actor(ActorType.EXTERNAL, sender_domain),
        reason_code="correlated_rfi_reply",
        evidence={"sender_domain": sender_domain, "provider_ref": provider_ref, "answer_chars": len(ans)},
        state_patch={"rfi_response": {"answer": ans, "sender_domain": sender_domain, "provider_ref": provider_ref}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)


# ── parse (strict schema + evidence spans) ────────────────────────────────────
def parse_quote(raw_body: str, commercial_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Deterministic strict-schema parse. The RAW body stays authoritative; each field carries an
    evidence span; a contradictory quantity lowers confidence. NEVER creates a PO."""
    body = raw_body or ""
    spans: List[Dict[str, str]] = []

    # quantity — collect every match (across forms) for contradiction detection; first is the quote qty
    qty_matches = list(_QTY_RE.finditer(body))
    qtys = [int((m.group("a") or m.group("b")).replace(",", "")) for m in qty_matches]
    distinct_qtys = sorted(set(qtys))
    quoted_quantity = qtys[0] if qtys else None
    if quoted_quantity is not None:
        spans.append({"field": "quoted_quantity", "text": qty_matches[0].group(0)})
    contradictory = len(distinct_qtys) > 1

    # unit price + currency — prefer a price in a per-unit context (so a line total can't masquerade as the
    # unit price); fall back to the first price found. Records the matched currency, not a hardcoded default.
    unit_amount_cents: Optional[int] = None
    currency = "AUD"
    price_matches = list(_PRICE_RE.finditer(body))
    chosen = None
    for m in price_matches:
        tail = body[m.end():m.end() + 12]
        if _PER_UNIT_RE.search(tail):
            chosen = m
            break
    chosen = chosen or (price_matches[0] if price_matches else None)
    if chosen is not None:
        amt = chosen.group("amt1") or chosen.group("amt2") or chosen.group("amt3")
        unit_amount_cents = _to_cents(amt)
        sym = chosen.group("sym")
        code = chosen.group("code1") or chosen.group("code2")
        currency = (code.upper() if code else _CURRENCY_SYMBOL.get(sym or "", "AUD"))
        spans.append({"field": "unit_amount", "text": chosen.group(0)})

    landed_unit_cost_cents: Optional[int] = None
    landed_cost_currency: Optional[str] = None
    landed = _LANDED_UNIT_RE.search(body)
    if landed is not None:
        landed_amount = landed.group("dollar") or landed.group("amount1") or landed.group("amount2")
        landed_unit_cost_cents = _to_cents(landed_amount)
        landed_cost_currency = str(landed.group("code1") or landed.group("code2") or "AUD").upper()
        spans.append({"field": "landed_unit_cost", "text": landed.group(0)})

    # lead time in days (a common alternative to an explicit dispatch date; also feeds quote comparison)
    lead_time_days: Optional[int] = None
    lm = _LEAD_RE.search(body)
    if lm:
        lead_time_days = int(lm.group("a") or lm.group("b"))
        spans.append({"field": "lead_time_days", "text": lm.group(0)})

    def _date(rx, field):
        m = rx.search(body)
        if not m:
            return None
        iso = _normalize_date(m.group(1))
        if iso:
            spans.append({"field": field, "text": m.group(0)})
        return iso

    dispatch_ready_at = _date(_DISPATCH_RE, "dispatch_ready_at")
    estimated_delivery_at = _date(_DELIVERY_RE, "estimated_delivery_at")
    quote_expires_at = _date(_EXPIRY_RE, "quote_expires_at")
    substitutions = [{"note": "substitute offered"}] if _SUBSTITUTE_RE.search(body) else []

    core = [quoted_quantity, unit_amount_cents, dispatch_ready_at, quote_expires_at]
    found = sum(1 for c in core if c is not None)
    confidence = round((found / len(core)) * (0.6 if contradictory else 1.0), 3)
    return {
        "quoted_quantity": quoted_quantity, "unit_amount_cents": unit_amount_cents,
        "currency": currency, "landed_unit_cost_cents": landed_unit_cost_cents,
        "landed_cost_currency": landed_cost_currency,
        "lead_time_days": lead_time_days, "dispatch_ready_at": dispatch_ready_at,
        "estimated_delivery_at": estimated_delivery_at, "quote_expires_at": quote_expires_at,
        "substitutions": substitutions, "contradictory": contradictory,
        "confidence": confidence, "evidence_spans": spans,
    }


def record_parsed(db, *, case_id: str, actor: Actor, parsed: Optional[Dict[str, Any]] = None,
                  tenant_id: str = "default", now_iso: Optional[str] = None,
                  trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """AGENT records the parse. No usable signal → quote_parse_failed; else supplier_response_parsed."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    inbound = (cur.state_json.get("inbound") if cur else None) or {}
    scope = (cur.state_json.get("draft", {}).get("commercial_scope") if cur else None) or {}
    pq = parsed if parsed is not None else parse_quote(inbound.get("raw_body", ""), scope)
    if not pq.get("confidence"):
        return workflow.transition(db, case_id=case_id, event="quote_parse_failed",
                                   actor=Actor(ActorType.SYSTEM, "parser"), reason_code="no_signal",
                                   evidence={"confidence": 0}, tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    return workflow.transition(
        db, case_id=case_id, event="supplier_response_parsed", actor=actor, reason_code="strict_schema_parse",
        evidence={"confidence": pq.get("confidence"), "evidence_spans": pq.get("evidence_spans"),
                  "contradictory": pq.get("contradictory")},
        state_patch={"parsed_quote": pq}, tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)


# ── validate (human; expired is hard-rejected) ────────────────────────────────
def validate_quote(db, *, case_id: str, actor: Actor, today: Optional[str] = None,
                   tenant_id: str = "default", now_iso: Optional[str] = None,
                   trace_id: Optional[str] = None) -> workflow.TransitionResult:
    """HUMAN validates. An expired quote is hard-rejected to quote_expired regardless of the human; an
    in-scope, unexpired quote advances to QUOTE_VALIDATED with a validation note."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    pq = (cur.state_json.get("parsed_quote") if cur else None) or {}
    scope = (cur.state_json.get("draft", {}).get("commercial_scope") if cur else None) or {}
    expiry = pq.get("quote_expires_at")
    day = today or (now_iso or "")[:10]
    if expiry and day and str(expiry) < str(day):
        return workflow.transition(db, case_id=case_id, event="quote_expired", actor=Actor(ActorType.SYSTEM, "clock"),
                                   reason_code="quote_past_expiry", evidence={"quote_expires_at": expiry, "as_of": day},
                                   tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    requested = int(scope.get("quantity") or 0)
    quoted = int(pq.get("quoted_quantity") or 0)
    note = {"in_scope": (quoted <= requested if requested else True),
            "shortfall_covered": quoted, "requested": requested,
            "confidence": pq.get("confidence"), "contradictory": pq.get("contradictory")}
    landed = int(pq.get("landed_unit_cost_cents") or 0)
    if landed:
        draft = (cur.state_json.get("draft") if cur else None) or {}
        inbound = (cur.state_json.get("inbound") if cur else None) or {}
        supplier_id = str(draft.get("supplier_ref") or "").strip()
        sku = str(scope.get("item_ref") or "").strip()
        provider_ref = str(inbound.get("provider_ref") or "").strip()
        currency = str(pq.get("landed_cost_currency") or pq.get("currency") or "").upper()
        source_record_id = provider_ref or f"case:{case_id}:supplier-quote"
        try:
            from src.app.services.supplier_catalog import record_validated_supplier_offer
            record_validated_supplier_offer(
                db,
                tenant_id=tenant_id,
                supplier_id=supplier_id,
                sku=sku,
                purchase_unit_cost_cents=int(pq.get("unit_amount_cents") or 0),
                landed_unit_cost_cents=landed,
                currency=currency,
                source_record_id=source_record_id,
                effective_from=now_iso or f"{day}T00:00:00+00:00",
                effective_to=pq.get("quote_expires_at"),
                confidence=float(pq.get("confidence") or 0),
                provenance_chain=[
                    f"fulfillment_case/{case_id}",
                    f"supplier_reply/{source_record_id}",
                    "human_validation/supplier_quote_validated",
                ],
            )
        except Exception:
            # Do not create a validated case whose authoritative landed economics
            # silently failed to materialize. The prior parsed state is already
            # durable; an operator can retry validation after the ledger is fixed.
            db.rollback()
            return workflow.TransitionResult(
                False, case_id, cur.state if cur else None,
                "supplier_offer_persist_failed", http_status=409,
            )
    return workflow.transition(
        db, case_id=case_id, event="supplier_quote_validated", actor=actor, reason_code="human_validated",
        evidence=note, state_patch={"validated_quote": {**pq, "validation": note}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
