"""Supplier-quote drafting (agnostic CORE) — the LLM-as-drafting-aid-inside-a-cage.

Fires the confidence-gated ``external_message_drafted`` transition. It runs ONLY post-commitment
(domain GATE 1), and it DRAFTS — it never sends (GATE 2 is a human). The cage:

  • recipient is resolved from the trusted-supplier ALLOWLIST + the ranked approved set — NEVER from
    buyer text (so a prompt-injected "email attacker@evil.com" cannot redirect the message);
  • the body is filled into a FIXED template's slots; a claim-safety guard rejects any price/commitment
    leakage (the supplier is asked to quote — we never state a price; the buyer never sees this body);
  • a "this is not a purchase order" footer is mandatory;
  • SCATTER-GATHER evidence (hippograph reliability · market-intel urgency · inventory shortfall ·
    external benchmark) is attached as DISCRETE evidence ids + a plain-English rationale, so the human
    reviewer sees WHY the agent drafted what it did (decision rationale, not hidden reasoning);
  • a content_hash pins the exact message — an edit changes the hash and (at the send gate) voids the
    prior approval.

Every external dependency is injectable (supplier ranking, evidence sources, LLM, allowlist) so the
drafter is deterministic + testable with no network. Vertical-blind: the template is DATA (from the
StoreProfile); core only fills opaque slots.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.app.services.fulfillment import workflow
from src.app.services.fulfillment.domain import Actor

# A generic, claim-free default template (real templates come from StoreProfile.supplier_message_templates).
# No product vocabulary, no price, no commitment language — just slots.
DEFAULT_TEMPLATE: Dict[str, str] = {
    "subject": "Availability and quote request — {item_ref} x {quantity} — {case_ref}",
    "body": (
        "Hello {supplier_name},\n\n"
        "Please confirm availability and provide a quote for {item_ref}, quantity {quantity}, "
        "required by {needed_by}.\n\n"
        "{urgency_note}\n\n"
        "This request does not constitute a purchase order.\n\n"
        "Regards,\nProcurement"
    ),
}
_NOT_A_PO = "this request does not constitute a purchase order"
# claim-safety: any currency/price-like token in the body is a leak (we ask the supplier to quote).
_PRICE_RE = re.compile(r"[$€£¥]\s?\d|\b\d+(?:\.\d{1,2})?\s?(?:usd|aud|eur|gbp|dollars?)\b", re.IGNORECASE)


@dataclass(frozen=True)
class DraftEvidence:
    source: str          # hippograph | market_intel | inventory | external_benchmark
    evidence_id: str
    summary: str
    provenance: str = "internal"   # internal | external:<source-with-provenance>
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SupplierDraft:
    recipient_ref: str
    recipient_domain: str
    subject: str
    body: str
    content_hash: str
    confidence: float
    rationale: List[str]
    evidence: List[Dict[str, Any]]
    commercial_scope: Dict[str, Any]   # {item_ref, quantity, estimated_value_cents} — never a unit cost

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def content_hash(subject: str, body: str) -> str:
    return hashlib.sha256(f"{subject}\n{body}".encode("utf-8")).hexdigest()[:32]


def _claim_safe(body: str) -> bool:
    return (_NOT_A_PO in (body or "").lower()) and (_PRICE_RE.search(body or "") is None)


# ── scatter-gather evidence (read-only; independent sources) ──────────────────
def gather_evidence(
    db,
    *,
    item_ref: str,
    case_state: Optional[Dict[str, Any]] = None,
    hippograph_fn: Optional[Callable] = None,
    market_fn: Optional[Callable] = None,
    benchmark_fn: Optional[Callable] = None,
    tenant_id: str = "default",
) -> List[DraftEvidence]:
    """Fan out across the four independent evidence sources (the design is parallel; this sync impl is
    sequential + best-effort — a failing source never blocks the draft). Each returns a discrete
    evidence id that lands on the trace."""
    ev: List[DraftEvidence] = []

    # inventory shortfall (from the case state — authoritative)
    avail = (case_state or {}).get("availability") or {}
    if avail:
        ev.append(DraftEvidence("inventory", f"INV-{uuid.uuid4().hex[:8]}",
                                f"shortfall {avail.get('shortfall')} of {avail.get('requested_qty')}",
                                payload={k: avail.get(k) for k in ("shortfall", "requested_qty", "in_stock")}))

    # hippograph supplier reliability / related context (best-effort — a dead source never blocks)
    for ins in _safe_list(hippograph_fn or _default_hippograph, db, item_ref, tenant_id)[:2]:
        ev.append(DraftEvidence("hippograph", f"HIP-{uuid.uuid4().hex[:8]}",
                                str(ins.get("summary") or ins.get("label") or "recall"), payload=ins))

    # market-intelligence urgency signal
    for f in _safe_list(market_fn or _default_market, db, item_ref, tenant_id)[:2]:
        ev.append(DraftEvidence("market_intel", f"MKT-{uuid.uuid4().hex[:8]}",
                                str(f.get("summary") or f.get("finding_type")), payload=f))

    # external benchmark (allowlisted + provenance-tagged) — internal sanity only, never sent
    b = _safe_one(benchmark_fn, item_ref) if benchmark_fn is not None else None
    if b:
        ev.append(DraftEvidence("external_benchmark", f"EXT-{uuid.uuid4().hex[:8]}",
                                str(b.get("summary") or "benchmark"),
                                provenance=f"external:{b.get('source', 'unknown')}", payload=b))
    return ev


def _safe_list(fn, *args) -> List[Dict[str, Any]]:
    try:
        return list(fn(*args) or [])
    except Exception:
        return []


def _safe_one(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None


def _default_hippograph(db, item_ref, tenant_id):
    from src.app.services.hippograph_feedback import build_hippograph_insights
    return build_hippograph_insights(db, seed_skus=[item_ref], top_k=4)


def _default_market(db, item_ref, tenant_id):
    from src.app.services.market_analysis import load_recent_findings
    fs = load_recent_findings(db, limit=20, tenant_id=tenant_id)
    return [{"finding_type": f.finding_type, "summary": f.summary, "severity": f.severity,
             "confidence": f.confidence, "entity_ref": f.entity_ref}
            for f in fs if (f.entity_ref or "").lower() == str(item_ref).lower() or f.entity_ref is None]


# ── supplier selection (from the APPROVED allowlist — never buyer text) ───────
def _default_rank(db, item_ref, tenant_id):
    try:
        from src.app.services.inventory_agent import InventoryAgent
        from src.app.services.supplier_catalog import domain_for_supplier
        best = InventoryAgent()._get_best_supplier(item_ref)  # type: ignore[attr-defined]
        if not best or not best.get("id"):
            return []
        # _get_best_supplier returns no domain; enrich from the allowlist (the approved-domain source).
        domain = domain_for_supplier(db, str(best["id"]))
        return [{**best, "domain": domain}] if domain else []
    except Exception:
        return []


def _default_allowlist(domain: str) -> bool:
    try:
        from src.app.services.supplier_domain_guard import is_trusted_supplier_domain
        return bool(is_trusted_supplier_domain(domain))
    except Exception:
        return False


def select_supplier(db, *, item_ref: str, rank_fn: Optional[Callable] = None,
                    allowlist_fn: Optional[Callable] = None, tenant_id: str = "default"):
    """Pick the top-ranked APPROVED supplier whose domain is on the allowlist. Returns
    (recipient_ref, recipient_domain, reliability, reason) or (None, ...) when none qualifies."""
    rank = rank_fn or _default_rank
    allow = allowlist_fn or _default_allowlist
    for cand in (rank(db, item_ref, tenant_id) or []):
        domain = str(cand.get("domain") or cand.get("supplier_domain") or "")
        if domain and allow(domain):
            return (str(cand.get("id") or cand.get("supplier_id") or "supplier"), domain,
                    float(cand.get("reliability") or cand.get("on_time_rate") or 0.0),
                    f"top approved supplier (reliability {cand.get('reliability') or cand.get('on_time_rate')})")
    return (None, "", 0.0, "no approved supplier on the allowlist")


# ── build the draft ───────────────────────────────────────────────────────────
def _urgency_note(evidence: List[DraftEvidence]) -> str:
    for e in evidence:
        if e.source == "market_intel" and "demand" in (e.summary or "").lower():
            return "We are seeing elevated demand; a firm dispatch date would be appreciated."
    return "A firm dispatch date would be appreciated."


def _confidence(reliability: float, evidence: List[DraftEvidence]) -> float:
    base = 0.55 + min(0.3, reliability * 0.3)
    if any(e.source == "market_intel" for e in evidence):
        base += 0.05
    if any(e.source == "hippograph" for e in evidence):
        base += 0.05
    return round(min(1.0, base), 3)


def build_draft(
    db,
    *,
    item_ref: str,
    quantity: int,
    case_ref: str,
    needed_by: str = "the stated deadline",
    estimated_value_cents: int = 0,
    case_state: Optional[Dict[str, Any]] = None,
    template: Optional[Dict[str, str]] = None,
    rank_fn: Optional[Callable] = None,
    allowlist_fn: Optional[Callable] = None,
    hippograph_fn: Optional[Callable] = None,
    market_fn: Optional[Callable] = None,
    benchmark_fn: Optional[Callable] = None,
    llm_fn: Optional[Callable] = None,
    tenant_id: str = "default",
) -> Optional[SupplierDraft]:
    """Build the exact supplier draft (no send). Returns None when no approved supplier qualifies."""
    recipient_ref, domain, reliability, supplier_reason = select_supplier(
        db, item_ref=item_ref, rank_fn=rank_fn, allowlist_fn=allowlist_fn, tenant_id=tenant_id)
    if not recipient_ref:
        return None  # → caller fires no_approved_supplier

    evidence = gather_evidence(db, item_ref=item_ref, case_state=case_state, hippograph_fn=hippograph_fn,
                               market_fn=market_fn, benchmark_fn=benchmark_fn, tenant_id=tenant_id)
    tmpl = template or DEFAULT_TEMPLATE
    slots = {"item_ref": item_ref, "quantity": quantity, "case_ref": case_ref,
             "supplier_name": recipient_ref, "needed_by": needed_by, "urgency_note": _urgency_note(evidence)}
    subject = str(tmpl.get("subject", DEFAULT_TEMPLATE["subject"])).format(**slots)
    body = str(tmpl.get("body", DEFAULT_TEMPLATE["body"])).format(**slots)

    # optional LLM polish — but ONLY accepted if it stays claim-safe; else keep the deterministic fill.
    if llm_fn is not None:
        cand = _safe_one(lambda: llm_fn(subject=subject, body=body, slots=slots)) or {}
        c_body = str(cand.get("body") or body)
        if _claim_safe(c_body):
            subject, body = str(cand.get("subject") or subject), c_body
    if not _claim_safe(body):
        return None  # refuse to draft an unsafe body (price/commitment leak or missing PO disclaimer)

    rationale = [
        f"supplier: {supplier_reason}",
        f"recipient resolved from allowlist ({domain}), not buyer input",
    ] + [f"{e.source}: {e.summary}" for e in evidence]
    return SupplierDraft(
        recipient_ref=recipient_ref, recipient_domain=domain, subject=subject, body=body,
        content_hash=content_hash(subject, body), confidence=_confidence(reliability, evidence),
        rationale=rationale, evidence=[asdict(e) for e in evidence],
        commercial_scope={"item_ref": item_ref, "quantity": int(quantity),
                          "estimated_value_cents": int(estimated_value_cents)},
    )


# ── wiring: record the draft via the workflow chokepoint ──────────────────────
def draft_and_record(db, *, case_id: str, actor: Actor, item_ref: str, quantity: int,
                     estimated_value_cents: int = 0, tenant_id: str = "default",
                     now_iso: Optional[str] = None, trace_id: Optional[str] = None, **draft_kw):
    """Build the draft + fire external_message_drafted (confidence-gated) through workflow.transition.
    Returns (TransitionResult, SupplierDraft|None). If no approved supplier, fires no_approved_supplier."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    case_state = cur.state_json if cur else {}
    draft = build_draft(db, item_ref=item_ref, quantity=quantity, case_ref=case_id,
                        estimated_value_cents=estimated_value_cents, case_state=case_state,
                        tenant_id=tenant_id, **draft_kw)
    if draft is None:
        res = workflow.transition(db, case_id=case_id, event="no_approved_supplier", actor=actor,
                                  reason_code="no_approved_supplier_on_allowlist", tenant_id=tenant_id,
                                  now_iso=now_iso, trace_id=trace_id)
        return res, None
    res = workflow.transition(
        db, case_id=case_id, event="external_message_drafted", actor=actor,
        reason_code="supplier_quote_drafted", confidence=draft.confidence,
        evidence={"content_hash": draft.content_hash, "recipient_domain": draft.recipient_domain,
                  "rationale": draft.rationale, "evidence_ids": [e["evidence_id"] for e in draft.evidence]},
        state_patch={"draft": draft.to_dict()}, tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    return res, draft


def request_supplier_approval(db, *, case_id: str, actor: Actor, tenant_id: str = "default",
                              now_iso: Optional[str] = None, trace_id: Optional[str] = None):
    """Fire approval_requested + enqueue a supplier_contact approval carrying the content_hash, recipient
    domain and commercial scope. Returns (TransitionResult, approval_id|None). The content_hash is what a
    later edit invalidates (the send gate checks it)."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    draft = (cur.state_json.get("draft") if cur else None) or {}
    res = workflow.transition(db, case_id=case_id, event="approval_requested", actor=actor,
                              reason_code="await_human_send_approval",
                              evidence={"content_hash": draft.get("content_hash")},
                              tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    approval_id = None
    if res.ok:
        try:
            from src.app.routers.approvals import enqueue_approval
            approval_id = enqueue_approval(
                capability="supplier_contact",
                payload={"case_id": case_id, "content_hash": draft.get("content_hash"),
                         "recipient_domain": draft.get("recipient_domain"),
                         "commercial_scope": draft.get("commercial_scope")},
                reason="Outbound supplier quote request — human review required (SUP-04)",
                created_by=actor.id)
        except Exception:
            approval_id = None
    return res, approval_id
