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

import re
import uuid
from typing import Any, Dict, List, Optional

from src.app.services.fulfillment import workflow
from src.app.services.fulfillment.domain import Actor, ActorType

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
    from src.app.services.fulfillment.transport import get_transport
    tx = transport or get_transport()
    recipient = str(draft.get("recipient_email") or draft.get("recipient_domain") or "")
    sent = tx.send(to=recipient, subject=str(draft.get("subject") or ""),
                   body=str(draft.get("body") or ""), idempotency_key=str(draft.get("content_hash") or ""))
    if getattr(sent, "status", "failed") != "sent":
        # the real transport did not transmit → do NOT record a send; the case stays APPROVED_TO_SEND.
        return workflow.TransitionResult(False, case_id, cur.state, "send_failed", http_status=502)
    provider_ref = sent.provider_ref
    return workflow.transition(
        db, case_id=case_id, event="external_message_sent", actor=actor,
        reason_code="human_approved_send",
        evidence={"content_hash": draft.get("content_hash"), "provider_ref": provider_ref,
                  "recipient": recipient, "recipient_domain": draft.get("recipient_domain"),
                  "transport": getattr(sent, "detail", "")},
        state_patch={"outbound": {"provider_ref": provider_ref, "recipient_domain": draft.get("recipient_domain"),
                                  "recipient": recipient, "content_hash": draft.get("content_hash"), "status": "sent",
                                  "transport": getattr(sent, "detail", "")}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)


# ── receive (correlate + verify, else quarantine) ─────────────────────────────
def receive_reply(db, *, case_id: str, raw_body: str, sender_domain: str, provider_ref: Optional[str] = None,
                  tenant_id: str = "default", now_iso: Optional[str] = None, trace_id: Optional[str] = None,
                  trusted_fn=None) -> workflow.TransitionResult:
    """Correlate an inbound reply to its case and verify the sender. Untrusted → quarantine."""
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
        "currency": currency, "lead_time_days": lead_time_days, "dispatch_ready_at": dispatch_ready_at,
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
    return workflow.transition(
        db, case_id=case_id, event="supplier_quote_validated", actor=actor, reason_code="human_validated",
        evidence=note, state_patch={"validated_quote": {**pq, "validation": note}},
        tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
