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
import json
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
        "{supplier_context}"
        "Please confirm availability and provide a quote for {item_ref}, quantity {quantity}, "
        "required by {needed_by}.\n\n"
        "{requirements_block}"
        "{urgency_note}\n\n"
        "Please reply to this address with your unit price, lead time, and how long the quote is valid.\n\n"
        "This request does not constitute a purchase order.\n\n"
        "Regards,\nProcurement"
    ),
}
_NOT_A_PO = "this request does not constitute a purchase order"
# claim-safety: any currency/price-like token in the body is a leak (we ask the supplier to quote).
_PRICE_RE = re.compile(r"[$€£¥]\s?\d|\b\d+(?:\.\d{1,2})?\s?(?:usd|aud|eur|gbp|dollars?)\b", re.IGNORECASE)
# unsupported / binding / manipulative commercial claims (deck: "no manipulative or deceptive claims",
# "no unsupported product promises"). Governance vocabulary, not product flavour — a default the profile
# may later extend. Critical once an LLM can rewrite the body: the model must not invent a guarantee/PO.
_PROHIBITED_CLAIM_RE = re.compile(
    r"\b(we guarantee|guaranteed|we promise|we commit\b|legally binding|we agree to pay|"
    r"best price guaranteed|lowest price|price match|exclusive deal|we will pay|"
    r"purchase order (is )?(confirmed|attached|enclosed|issued)|this (is|confirms) (a|our) purchase order|"
    r"order (is )?confirmed|payment (is )?guaranteed)\b", re.IGNORECASE)
# a URL in an outbound supplier email is an exfiltration / phishing vector if an LLM injected it.
_URL_RE = re.compile(r"https?://|www\.|\bbit\.ly\b", re.IGNORECASE)
# any email address in the body that is NOT on the resolved supplier domain = a redirect/CC injection.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@([\w-]+\.[\w.-]+)\b")

# Profile EXTENSION of the prohibited-claim floor: a vertical may ADD prohibited patterns via the
# `prohibited_claim_patterns` slot (a list of regex strings — e.g. counterfeit/grey-market over-promises
# specific to that vertical). The hardcoded _PROHIBITED_CLAIM_RE floor ALWAYS applies, so the profile can
# only TIGHTEN the send-cage, never weaken it. A malformed profile regex is skipped (fail-safe: it must
# never crash or disable the cage). Compiled patterns are cached per profile_id; reset_prohibited_cache()
# clears it between profile swaps (wired into the test profile-cache reset).
_PROHIBITED_PROFILE_CACHE: Dict[str, List["re.Pattern[str]"]] = {}


def _safe_compile(pattern: str) -> Optional["re.Pattern[str]"]:
    """Compile a profile-supplied regex, or return None if it is malformed (fail-safe: a bad pattern is
    dropped, never crashes the send-cage). Returning None keeps the handler observable (no silent swallow)."""
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return None


def _profile_prohibited_patterns(profile_id: Optional[str] = None) -> List["re.Pattern[str]"]:
    key = str(profile_id or "")
    cached = _PROHIBITED_PROFILE_CACHE.get(key)
    if cached is not None:
        return cached
    raw: Any = []
    try:
        from src.app.platform.store_profile import profile_slot
        raw = profile_slot("prohibited_claim_patterns", profile_id=profile_id, default=[]) or []
    except Exception:
        raw = []
    items = raw if isinstance(raw, (list, tuple)) else []
    compiled = [pat for pat in (_safe_compile(str(p)) for p in items) if pat is not None]
    _PROHIBITED_PROFILE_CACHE[key] = compiled
    return compiled


def reset_prohibited_cache() -> None:
    """Test hook — clear the compiled profile-extension cache so a profile swap is honoured next read."""
    _PROHIBITED_PROFILE_CACHE.clear()


def claim_safety_reason(body: str, *, recipient_domain: Optional[str] = None) -> Optional[str]:
    """The reason a body is UNSAFE to send, or None if safe. Single source of the send-cage policy; used by
    _claim_safe and surfaced for observability. Hardened for LLM-rewritten bodies: rejects price/PO leaks,
    a missing not-a-PO footer, unsupported/binding claims, URLs, and any foreign email address (a
    redirect/CC injection — the recipient is resolved from the allowlist, never from the body)."""
    b = body or ""
    if _NOT_A_PO not in b.lower():
        return "missing_not_a_po_footer"
    if _PRICE_RE.search(b):
        return "price_or_currency_leak"
    if _PROHIBITED_CLAIM_RE.search(b):
        return "unsupported_or_binding_claim"
    for _pat in _profile_prohibited_patterns():  # vertical EXTENSIONS to the floor (additive only)
        if _pat.search(b):
            return "unsupported_or_binding_claim"
    if _URL_RE.search(b):
        return "contains_url"
    if recipient_domain:
        rd = str(recipient_domain).strip().lower()
        for m in _EMAIL_RE.finditer(b):
            if m.group(1).strip().lower() != rd:
                return "foreign_email_address"
    return None


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

    recipient_email: Optional[str] = None
    completeness: Optional[Dict[str, Any]] = None  # {complete: bool, reason: str|None} — RFQ field coverage

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def content_hash(subject: str, body: str) -> str:
    return hashlib.sha256(f"{subject}\n{body}".encode("utf-8")).hexdigest()[:32]


def _claim_safe(body: str, *, recipient_domain: Optional[str] = None) -> bool:
    return claim_safety_reason(body, recipient_domain=recipient_domain) is None


def _supplier_polish_enabled() -> bool:
    """Flag for the caged LLM tone-polish (default OFF — the deterministic template ships safely without it)."""
    import os
    return str(os.getenv("SUPPLIER_DRAFT_LLM_POLISH", "")).strip().lower() in ("1", "true", "yes", "on")


# ── scatter-gather evidence (read-only; independent sources) ──────────────────
def gather_evidence(
    db,
    *,
    item_ref: str,
    case_state: Optional[Dict[str, Any]] = None,
    recipient_domain: str = "",
    hippograph_fn: Optional[Callable] = None,
    market_fn: Optional[Callable] = None,
    benchmark_fn: Optional[Callable] = None,
    inbox_fn: Optional[Callable] = None,
    tenant_id: str = "default",
) -> List[DraftEvidence]:
    """Fan out across the independent evidence sources (the design is parallel; this sync impl is
    sequential + best-effort — a failing source never blocks the draft). Each returns a discrete
    evidence id that lands on the trace."""
    ev: List[DraftEvidence] = []

    # inventory shortfall (from the case state — authoritative)
    avail = (case_state or {}).get("availability") or {}
    if avail:
        ev.append(DraftEvidence("inventory", f"INV-{uuid.uuid4().hex[:8]}",
                                f"shortfall {avail.get('shortfall')} of {avail.get('requested_qty')}",
                                payload={k: avail.get(k) for k in ("shortfall", "requested_qty", "in_stock")}))

    # multi-location availability (Phase 1) — per-location stock + the transfer plan that can cover the
    # preferred-location gap BEFORE sourcing externally. Already gathered onto the case; surfaced here so the
    # operator sees "could we move stock instead?" before approving the RFQ. No new I/O.
    net = avail.get("network") if isinstance(avail, dict) else None
    if isinstance(net, dict) and (net.get("by_location") or net.get("transfer_plan")):
        tp = [t for t in (net.get("transfer_plan") or []) if isinstance(t, dict)]
        moved = sum(int(t.get("qty") or 0) for t in tp)
        n_locs = len(net.get("by_location") or {})
        summary = (f"network has {net.get('total_in_network')} across {n_locs} locations; "
                   f"transfer {moved} to cover the preferred-location gap" if tp
                   else f"network has {net.get('total_in_network')} across {n_locs} locations")
        ev.append(DraftEvidence("multi_location", f"LOC-{uuid.uuid4().hex[:8]}", summary,
                                payload={k: net.get(k) for k in ("total_in_network", "by_location",
                                                                 "transfer_plan", "shortfall")}))

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

    # supplier history (READ-ONLY) — recent dealings with the ALREADY-resolved recipient domain, so the
    # human reviewer sees "last invoice / contact" context. Bounded to the allowlist domain (never buyer
    # text); only added when something is actually known. Default off when no inbox source / no history.
    if recipient_domain:
        ctx = _safe_one(inbox_fn or _default_inbox, recipient_domain, tenant_id)
        if ctx:
            ev.append(DraftEvidence("supplier_history", f"SUP-HIST-{uuid.uuid4().hex[:8]}",
                                    str(ctx.get("summary") or "history"), payload=ctx))
    return ev


def _default_inbox(recipient_domain, tenant_id):
    """Read-only supplier-history context for the resolved domain (Supplier_Inbox_Reader). None if none."""
    from src.app.services.supplier_inbox_reader import recent_supplier_context
    ctx = recent_supplier_context(domain=recipient_domain, tenant_id=tenant_id)
    return ctx.to_dict() if ctx else None


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


def ranked_approved_suppliers(db, *, item_ref: str, top_n: int = 3, rank_fn: Optional[Callable] = None,
                              allowlist_fn: Optional[Callable] = None, tenant_id: str = "default"):
    """Top-N APPROVED suppliers whose domain is on the allowlist, ranked. Each entry is
    (recipient_ref, recipient_domain, reliability, reason). Shared by select_supplier (top-1) and the
    competitive RFQ fan-out (top-N), so both resolve recipients the SAME way (allowlist only, never buyer
    input). Returns [] when none qualifies."""
    rank = rank_fn or _default_rank
    allow = allowlist_fn or _default_allowlist
    out = []
    for cand in (rank(db, item_ref, tenant_id) or []):
        domain = str(cand.get("domain") or cand.get("supplier_domain") or "")
        if domain and allow(domain):
            out.append((str(cand.get("id") or cand.get("supplier_id") or "supplier"), domain,
                        float(cand.get("reliability") or cand.get("on_time_rate") or 0.0),
                        f"approved supplier (reliability {cand.get('reliability') or cand.get('on_time_rate')})"))
            if len(out) >= max(1, int(top_n)):
                break
    return out


def select_supplier(db, *, item_ref: str, rank_fn: Optional[Callable] = None,
                    allowlist_fn: Optional[Callable] = None, tenant_id: str = "default"):
    """Pick the top-ranked APPROVED supplier whose domain is on the allowlist. Returns
    (recipient_ref, recipient_domain, reliability, reason) or (None, ...) when none qualifies."""
    top = ranked_approved_suppliers(db, item_ref=item_ref, top_n=1, rank_fn=rank_fn,
                                    allowlist_fn=allowlist_fn, tenant_id=tenant_id)
    if top:
        recipient_ref, domain, reliability, _reason = top[0]
        return (recipient_ref, domain, reliability,
                f"top approved supplier (reliability {reliability})")
    return (None, "", 0.0, "no approved supplier on the allowlist")


# ── build the draft ───────────────────────────────────────────────────────────
def _urgency_note(evidence: List[DraftEvidence]) -> str:
    for e in evidence:
        if e.source == "market_intel" and "demand" in (e.summary or "").lower():
            return "We are seeing elevated demand; a firm dispatch date would be appreciated."
    return "A firm dispatch date would be appreciated."


def _supplier_context_note(evidence: List[DraftEvidence]) -> str:
    """A short, claim-safe relationship line drawn from prior dealings — personalises the ask to a supplier
    we have history with. Qualitative ONLY (no amounts), so no internal pricing leaks into the body."""
    for e in evidence:
        if e.source == "supplier_history" and int((e.payload or {}).get("observations") or 0) > 0:
            return "Thank you for your continued partnership. "
    return ""


def _requirements_block(case_state: Optional[Dict[str, Any]]) -> str:
    """Render the buyer's stated requirements (way-1) as claim-safe RFQ bullets so the supplier knows what
    to quote against. BUDGET is deliberately excluded — it is internal-only and must never anchor supplier
    pricing. Returns '' when the case carries no requirements (graceful no-op)."""
    reqs = (case_state or {}).get("requirements") if isinstance(case_state, dict) else None
    if not isinstance(reqs, dict):
        return ""
    bullets: List[str] = []
    uc = str(reqs.get("use_case") or "").strip()
    if uc:
        bullets.append(f"Intended use: {uc}")
    specs = reqs.get("specs")
    if isinstance(specs, list) and specs:
        bullets.append("Required specs: " + ", ".join(str(s) for s in specs[:6]))
    days = reqs.get("needed_within_days")
    if days:
        bullets.append(f"Needed within: {int(days)} days")
    if not bullets:
        return ""
    return "Key requirements:\n" + "\n".join(f"- {b}" for b in bullets) + "\n\n"


def _resolve_supplier_name(db, domain: str, tenant_id: str) -> Optional[str]:
    """A human-friendly supplier name for the greeting (the kyv legal/trading name), resolved from the
    already-approved domain. Falls back to None so the caller keeps the supplier ref. Never raises."""
    try:
        from src.app.security.kyv_registry import lookup_vendor_by_domain
        v = lookup_vendor_by_domain(tenant_id=tenant_id, domain=domain) or {}
        return (str(v.get("legal_name") or v.get("trading_name") or "").strip()) or None
    except Exception:
        return None


def draft_send_gate(draft: Dict[str, Any], *, min_confidence: float = 0.6) -> Dict[str, Any]:
    """Deterministic pre-send policy gate — answers "should this draft be sent to the supplier at all?",
    independent of and PRIOR to the human send gate (GATE 2). Returns
    {decision: allow|block|needs_info, blocking: [...], reasons: [...]}:

      • block      → a hard safety failure (no resolved recipient, or a price/PO leak). Never sendable.
      • needs_info → structurally incomplete (missing commercial scope, low confidence, no evidence) — get
                     more information (from the buyer/case, or via a scoped supplier RFI) before sending.
      • allow      → safe + complete enough to put in front of the human approver (GATE 2 still applies).

    Pure function over the draft dict (no I/O); safe to compute anywhere and surface to the operator."""
    d = draft or {}
    blocking: List[str] = []
    needs: List[str] = []
    if not str(d.get("recipient_email") or d.get("recipient_domain") or "").strip():
        blocking.append("no_recipient")
    if not _claim_safe(str(d.get("body") or ""), recipient_domain=d.get("recipient_domain")):
        blocking.append("claim_unsafe")  # price/PO/URL/foreign-recipient leak or missing not-a-PO footer
    scope = d.get("commercial_scope") or {}
    if not str(scope.get("item_ref") or "").strip() or int(scope.get("quantity") or 0) <= 0:
        needs.append("missing_commercial_scope")
    try:
        if float(d.get("confidence") or 0.0) < float(min_confidence):
            needs.append("low_confidence")
    except (TypeError, ValueError):
        needs.append("low_confidence")
    if not (d.get("evidence") or []):
        needs.append("no_evidence")
    decision = "block" if blocking else ("needs_info" if needs else "allow")
    return {"decision": decision, "blocking": blocking, "reasons": needs}


def _confidence(reliability: float, evidence: List[DraftEvidence]) -> float:
    base = 0.55 + min(0.3, reliability * 0.3)
    if any(e.source == "market_intel" for e in evidence):
        base += 0.05
    if any(e.source == "hippograph" for e in evidence):
        base += 0.05
    return round(min(1.0, base), 3)


class _SafeDict(dict):
    def __missing__(self, key):  # tolerate a template slot we didn't populate (no KeyError on .format)
        return ""


def _safe_format(template: str, slots: Dict[str, Any]) -> str:
    try:
        return str(template).format_map(_SafeDict(slots))
    except Exception:
        return str(template)


def _sku_description(db, item_ref: str, tenant_id: str = "default") -> str:
    """Full line-item description for the RFQ (product name + key specs) so the supplier knows the EXACT
    unit, not a bare SKU code. Vertical-blind: the spec dimensions come from the active StoreProfile (the
    same slot narration uses), never hardcoded here — and price is NEVER included (cage). Falls back to the
    item_ref when the catalog has no matching row."""
    try:
        from sqlalchemy import text as _t
        row = db.execute(_t("SELECT name, specs FROM products WHERE sku = :s AND COALESCE(active,1)=1 LIMIT 1"),
                         {"s": str(item_ref)}).fetchone()
        if not row:
            return str(item_ref)
        name = str(row[0] or item_ref)
        specs = row[1]
        if isinstance(specs, str):
            try:
                specs = json.loads(specs)
            except Exception:
                specs = {}
        specs = specs if isinstance(specs, dict) else {}
        parts: List[str] = []
        try:
            from src.app.services.narration_tradeoff import _format_dimension, spec_dimensions
            for dim in spec_dimensions():
                line = _format_dimension(dim, specs)  # "Label: val{unit}" — no price, profile-defined keys
                if line:
                    parts.append(line)
        except Exception:
            parts = []
        desc = name if not parts else f"{name} — " + " | ".join(parts)
        return f"{desc} [{item_ref}]"
    except Exception:
        return str(item_ref)


# a slot left at one of these vague placeholders is NOT a real value — it counts as missing for completeness
# (the whole point of WS-B is to stop sending an RFQ that says "the stated deadline" with no actual date).
_VAGUE_SLOT_VALUES = {"the stated deadline"}


def no_supplier_alternatives(db, *, item_ref: str, quantity: int, case_state: Optional[Dict[str, Any]],
                             tenant_id: str = "default") -> Optional[List[Dict[str, Any]]]:
    """Fulfilment alternatives when there's NO approved supplier for the SKU — so it isn't a dead-end.
    Offers substitutes (that may have coverage) + take-available; NOT 'source from supplier' (there is
    none). Best-effort; vertical-blind (substitutes ranked by the profile's attributes)."""
    try:
        avail = (case_state or {}).get("availability") or {}
        reqs = (case_state or {}).get("requirements") or {}
        budget = reqs.get("budget") or {}
        in_stock = int(avail.get("in_stock") or 0)
        from src.app.services.substitute_generator import find_substitutes
        subs = find_substitutes(db, item_ref, use_case=reqs.get("use_case"), budget_min=budget.get("min"),
                                budget_max=budget.get("max"), limit=3, tenant_id=tenant_id) or []
        opts: List[Dict[str, Any]] = []
        for s in subs:
            if not s.get("sku"):
                continue
            opts.append({"option_id": f"substitute:{s['sku']}", "type": "substitute",
                         "title": f"Switch to {s.get('name') or s['sku']}",
                         "detail": str(s.get("tradeoff") or "a comparable alternative that may have supplier coverage"),
                         "sku": s["sku"], "price_cents": s.get("price_cents")})
        if 0 < in_stock < int(quantity or 0):
            opts.append({"option_id": "reduce_to_available", "type": "reduce_to_available",
                         "title": f"Take the {in_stock} available now",
                         "detail": f"We can fulfil {in_stock} from stock now; the remainder has no approved supplier yet."})
        return opts or None
    except Exception:
        return None


def rfq_completeness_reason(slots: Dict[str, Any], required_fields: Optional[List[str]] = None) -> Optional[str]:
    """The reason an RFQ draft is INCOMPLETE (a missing/placeholder required field), or None if complete.
    Used for the operator badge and (WS-C) as a gate before autonomous send — an incomplete RFQ must not
    auto-send. A field set to a vague placeholder (e.g. 'the stated deadline') counts as missing."""
    required = required_fields or ["sku_description", "deadline_date", "ship_to", "quantity"]
    missing = []
    for f in required:
        v = str(slots.get(f) or "").strip()
        if not v or v.lower() in _VAGUE_SLOT_VALUES:
            missing.append(f)
    return ("missing_rfq_fields:" + ",".join(missing)) if missing else None


def _rfq_term_slots(profile_fn: Optional[Callable]) -> Dict[str, Any]:
    """Commercial-term DATA from the active StoreProfile (quote-validity / warranty / payment / ship-to).
    Core stays vertical-blind — the phrasing lives in the profile."""
    def _p(key, default):
        try:
            return (profile_fn(key, default=default) if profile_fn else default)
        except Exception:
            return default
    return {
        "quote_validity_days": _p("rfq_quote_validity_days", 14),
        "warranty_preference": str(_p("rfq_warranty_preference", "") or ""),
        "payment_terms_ask": str(_p("rfq_payment_terms_ask", "") or ""),
        "ship_to_region": str(_p("rfq_ship_to_region", "") or ""),
        "bulk_threshold": int(_p("rfq_bulk_threshold", 5) or 5),
    }


def _line_items_block(db, lines: List[Dict[str, Any]], tenant_id: str) -> str:
    """A multi-line RFQ item block (one supplier, several SKUs) — each line's full description + qty. Empty
    when there are no usable lines. Vertical-blind (reuses the profile-driven _sku_description)."""
    parts: List[str] = []
    for ln in (lines or []):
        if not isinstance(ln, dict):
            continue
        ir = str(ln.get("item_ref") or ln.get("sku") or "").strip()
        q = int(ln.get("quantity") or ln.get("requested_qty") or ln.get("shortfall") or 0)
        if not ir or q <= 0:
            continue
        parts.append(f"  - {_sku_description(db, ir, tenant_id)} ({q} units)")
    return ("the following items:\n" + "\n".join(parts)) if parts else ""


def _build_rfq_slots(db, *, item_ref: str, quantity: int, case_ref: str, case_state: Optional[Dict[str, Any]],
                     supplier_name: str, needed_by: str, evidence: List["DraftEvidence"],
                     profile_fn: Optional[Callable], tenant_id: str,
                     lines: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Build the superset slot dict for BOTH the rich supplier_rfq template and the legacy DEFAULT_TEMPLATE.
    Deterministic: catalog (SKU desc) + case (deadline/qty) + profile (terms). No price, no commitment."""
    terms = _rfq_term_slots(profile_fn)
    reqs = (case_state or {}).get("requirements") if isinstance(case_state, dict) else {}
    reqs = reqs if isinstance(reqs, dict) else {}
    # real deadline: case needed_by (a date) > the needed_by arg (if not the vague default) > derived
    deadline = str(reqs.get("needed_by") or "").strip()
    if not deadline and needed_by and needed_by != "the stated deadline":
        deadline = str(needed_by)
    if not deadline:
        days = reqs.get("needed_within_days")
        deadline = (f"within {int(days)} days" if days else "the stated deadline")
    ship_to = str(reqs.get("ship_to") or terms["ship_to_region"] or "").strip()
    bulk = int(quantity or 0) >= terms["bulk_threshold"]
    # multi-line (one supplier, several SKUs) → render a line-items block; else the single SKU description.
    _multi = [l for l in (lines or []) if isinstance(l, dict) and (l.get("item_ref") or l.get("sku"))]
    sku_desc = _line_items_block(db, _multi, tenant_id) if _multi else _sku_description(db, item_ref, tenant_id)
    if not sku_desc:  # lines provided but none usable → fall back to the primary item
        sku_desc = _sku_description(db, item_ref, tenant_id)
        _multi = []
    # a COMPACT label for the subject line (the full block with newlines must never go in a subject).
    item_label = (f"{len(_multi)} items" if len(_multi) > 1 else item_ref)
    return {
        # legacy DEFAULT_TEMPLATE slots
        "item_ref": item_ref, "quantity": quantity, "case_ref": case_ref, "supplier_name": supplier_name,
        "needed_by": deadline, "urgency_note": _urgency_note(evidence),
        "supplier_context": _supplier_context_note(evidence), "requirements_block": _requirements_block(case_state),
        # rich supplier_rfq slots
        "sku_description": sku_desc, "item_label": item_label, "deadline_date": deadline, "ship_to": ship_to,
        "ship_to_line": (f"- Ship to: {ship_to}\n" if ship_to else ""),
        "quote_validity_days": terms["quote_validity_days"],
        "warranty_line": (f"- {terms['warranty_preference']}\n" if terms["warranty_preference"] else ""),
        "payment_terms_line": (f"- {terms['payment_terms_ask']}\n" if terms["payment_terms_ask"] else ""),
        "volume_discount_ask": (f", including your best volume/tier pricing for {quantity} units" if bulk else ""),
    }


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
    inbox_fn: Optional[Callable] = None,
    llm_fn: Optional[Callable] = None,
    supplier_override: Optional[tuple] = None,
    lines: Optional[List[Dict[str, Any]]] = None,
    tenant_id: str = "default",
) -> Optional[SupplierDraft]:
    """Build the exact supplier draft (no send). Returns None when no approved supplier qualifies.

    ``supplier_override`` = (recipient_ref, domain, reliability, reason) bypasses select_supplier so the
    RFQ fan-out can draft for a SPECIFIC top-N supplier. It is still trusted only via the resolved domain
    (the caller resolves it from the allowlist, never buyer input), so the send-cage is unchanged."""
    if supplier_override is not None:
        recipient_ref, domain, reliability, supplier_reason = supplier_override
    else:
        recipient_ref, domain, reliability, supplier_reason = select_supplier(
            db, item_ref=item_ref, rank_fn=rank_fn, allowlist_fn=allowlist_fn, tenant_id=tenant_id)
    if not recipient_ref:
        return None  # → caller fires no_approved_supplier

    evidence = gather_evidence(db, item_ref=item_ref, case_state=case_state, recipient_domain=domain,
                               hippograph_fn=hippograph_fn, market_fn=market_fn, benchmark_fn=benchmark_fn,
                               inbox_fn=inbox_fn, tenant_id=tenant_id)
    # Per-(supplier, SKU) commercial terms (WS-1): MOQ pre-check + volume price-break nudge. Both are
    # non-blocking advisories surfaced on the draft so the operator sees the risk + the upsell BEFORE
    # sending. Vertical-blind (qty / cents / % only).
    try:
        from src.app.services.supplier_catalog import price_break_advisory, supplier_terms
        _terms = supplier_terms(db, recipient_ref, item_ref, tenant_id=tenant_id)
    except Exception:
        _terms = {}
    _moq = _terms.get("moq")
    if _moq and int(quantity) < int(_moq):
        evidence.append(DraftEvidence(
            "moq_risk", f"MOQ-{uuid.uuid4().hex[:8]}",
            f"requested {quantity} is below this supplier's minimum order quantity ({_moq}); they may "
            f"decline or require a minimum order — consider fulfilling available stock now and sourcing "
            f"only if the MOQ is acceptable",
            payload={"requested_qty": int(quantity), "supplier_moq": int(_moq)}))
    _pb = price_break_advisory(int(quantity), _terms) if _terms else None
    if _pb:
        evidence.append(DraftEvidence("price_break", f"PB-{uuid.uuid4().hex[:8]}", _pb,
                                      payload={"requested_qty": int(quantity),
                                               "price_breaks": _terms.get("price_breaks")}))
    # active StoreProfile supplies the RFQ template + commercial-term DATA — core stays vertical-blind.
    def _profile_fn(key, default=None):
        try:
            from src.app.platform.store_profile import profile_slot
            return profile_slot(key, default=default)
        except Exception:
            return default

    supplier_name = _resolve_supplier_name(db, domain, tenant_id) or recipient_ref
    slots = _build_rfq_slots(db, item_ref=item_ref, quantity=quantity, case_ref=case_ref,
                             case_state=case_state, supplier_name=supplier_name, needed_by=needed_by,
                             evidence=evidence, profile_fn=_profile_fn, tenant_id=tenant_id, lines=lines)
    # template precedence: caller-injected > profile supplier_rfq > built-in default. _safe_format tolerates
    # a slot the chosen template doesn't reference (the two templates have different slot shapes).
    tmpl = template or _profile_fn("supplier_rfq", default=None) or DEFAULT_TEMPLATE
    if not isinstance(tmpl, dict):
        tmpl = DEFAULT_TEMPLATE
    subject = _safe_format(tmpl.get("subject", DEFAULT_TEMPLATE["subject"]), slots)
    body = _safe_format(tmpl.get("body", DEFAULT_TEMPLATE["body"]), slots)

    # optional LLM polish — AI proposes, the cage authorizes: the rewrite is ACCEPTED ONLY if it passes the
    # (now broadened) claim-safety gate against the RESOLVED domain; any prompt-injected price/PO/URL/foreign
    # recipient → discard the LLM output, keep the deterministic fill. _safe_one bounds exceptions; llm_fn
    # must bound its own network timeout (no silent hang).
    if llm_fn is not None:
        cand = _safe_one(lambda: llm_fn(subject=subject, body=body, slots=slots)) or {}
        c_body = str(cand.get("body") or body)
        if _claim_safe(c_body, recipient_domain=domain):
            subject, body = str(cand.get("subject") or subject), c_body
    if not _claim_safe(body, recipient_domain=domain):
        return None  # refuse to draft an unsafe body (price/commitment leak or missing PO disclaimer)

    rationale = [
        f"supplier: {supplier_reason}",
        f"recipient resolved from allowlist ({domain}), not buyer input",
    ] + [f"{e.source}: {e.summary}" for e in evidence]
    recipient_email = None
    for e in evidence:
        if e.source != "supplier_history":
            continue
        candidate = str((e.payload or {}).get("contact_email") or "").strip()
        if candidate and candidate.lower().endswith(f"@{domain.lower()}"):
            recipient_email = candidate
            break
    required = _profile_fn("rfq_required_fields", default=None) or \
        ["sku_description", "deadline_date", "ship_to", "quantity"]
    comp_reason = rfq_completeness_reason(slots, required)
    completeness = {"complete": comp_reason is None, "reason": comp_reason, "required_fields": list(required)}
    return SupplierDraft(
        recipient_ref=recipient_ref, recipient_domain=domain, subject=subject, body=body,
        content_hash=content_hash(subject, body), confidence=_confidence(reliability, evidence),
        rationale=rationale, evidence=[asdict(e) for e in evidence],
        commercial_scope={"item_ref": item_ref, "quantity": int(quantity),
                          "estimated_value_cents": int(estimated_value_cents),
                          **({"lines": [{"item_ref": str(l.get("item_ref") or l.get("sku") or ""),
                                         "quantity": int(l.get("quantity") or l.get("requested_qty") or
                                                          l.get("shortfall") or 0)}
                                        for l in lines if isinstance(l, dict)]} if lines else {})},
        recipient_email=recipient_email, completeness=completeness,
    )


# ── wiring: record the draft via the workflow chokepoint ──────────────────────
def _emit_supplier_selection_trace(
    *,
    trace_id: Optional[str],
    case_id: str,
    draft: SupplierDraft,
    tenant_id: str = "default",
) -> None:
    """Expose supplier selection in Decision Trace. Best-effort only; procurement must not depend on trace I/O."""
    if not trace_id:
        return
    scope = draft.commercial_scope or {}
    item_ref = str(scope.get("item_ref") or "").strip()
    terms: Dict[str, Any] = {}
    try:
        from src.app.models.db import db_session
        from src.app.services.supplier_catalog import supplier_terms
        with db_session() as _db:
            terms = supplier_terms(_db, draft.recipient_ref, item_ref, tenant_id=tenant_id) if item_ref else {}
    except Exception:
        terms = {}
    payload = {
        "case_id": case_id,
        "item_ref": item_ref,
        "quantity": scope.get("quantity"),
        "supplier_ref": draft.recipient_ref,
        "recipient_domain": draft.recipient_domain,
        "recipient_email": draft.recipient_email,
        "content_hash": draft.content_hash,
        "confidence": draft.confidence,
        "supplier_terms": {
            "moq": terms.get("moq"),
            "min_order_value_cents": terms.get("min_order_value_cents"),
            "lead_time_days": terms.get("lead_time_days"),
            "region": terms.get("region"),
            "on_time_rate": terms.get("on_time_rate"),
            "contract_status": terms.get("contract_status"),
            "price_breaks": terms.get("price_breaks") or [],
        },
        "rationale": list(draft.rationale or [])[:12],
        "evidence": [
            {
                "source": e.get("source"),
                "evidence_id": e.get("evidence_id"),
                "summary": e.get("summary"),
                "payload": e.get("payload") or {},
            }
            for e in (draft.evidence or [])
            if isinstance(e, dict)
            and e.get("source") in {"moq_risk", "price_break", "supplier_history", "inventory"}
        ],
        "idempotency_key": f"supplier-selection:{case_id}:{draft.content_hash}",
    }
    try:
        from src.app.services.decision_log import log_trace_event
        log_trace_event(trace_id=trace_id, event_type="supplier_selected", source_type="agent",
                        source_id="Supplier_Selection_Agent", target_type="fulfillment_case",
                        target_id=case_id, payload=payload, durable=True)
    except Exception:
        return


def draft_and_record(db, *, case_id: str, actor: Actor, item_ref: str, quantity: int,
                     estimated_value_cents: int = 0, tenant_id: str = "default",
                     now_iso: Optional[str] = None, trace_id: Optional[str] = None, **draft_kw):
    """Build the draft + fire external_message_drafted (confidence-gated) through workflow.transition.
    Returns (TransitionResult, SupplierDraft|None). If no approved supplier, fires no_approved_supplier."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    case_state = cur.state_json if cur else {}
    # Phase 3: when qualification is required, no RFQ may be drafted until a human has verified the buyer is
    # serious (FULFILLMENT_REQUIRE_QUALIFICATION). The buyer-clarification happens in the escalation room.
    from src.app.services.fulfillment.buyer_qualification import qualification_required, is_qualified
    if qualification_required() and not is_qualified(case_state):
        return workflow.TransitionResult(False, case_id, cur.state if cur else None,
                                         "buyer_not_qualified", http_status=409), None
    # Flag-gated caged LLM tone-polish (default OFF). build_draft re-validates the rewrite through the
    # broadened claim-safety gate + deterministic fallback, so enabling this can only improve tone, never
    # weaken safety. An explicitly-injected llm_fn (tests) is respected as-is.
    if "llm_fn" not in draft_kw and _supplier_polish_enabled():
        from src.app.services.fulfillment.supplier_polish import polish_supplier_draft
        draft_kw["llm_fn"] = polish_supplier_draft
    # multi-line case (one supplier, several SKUs) → the RFQ lists every line. The lines are persisted on
    # the case (order_lines) by the multi-line creation path; a single-line case has none (unchanged).
    if "lines" not in draft_kw:
        _ol = case_state.get("order_lines") if isinstance(case_state, dict) else None
        if isinstance(_ol, list) and len(_ol) > 1:
            draft_kw["lines"] = _ol
    draft = build_draft(db, item_ref=item_ref, quantity=quantity, case_ref=case_id,
                        estimated_value_cents=estimated_value_cents, case_state=case_state,
                        tenant_id=tenant_id, **draft_kw)
    if draft is None:
        # Not a dead-end: attach fulfilment alternatives (substitutes with coverage / take-available) so the
        # buyer/operator has a next step instead of a blocked case.
        _alts = no_supplier_alternatives(db, item_ref=item_ref, quantity=quantity, case_state=case_state,
                                         tenant_id=tenant_id)
        res = workflow.transition(db, case_id=case_id, event="no_approved_supplier", actor=actor,
                                  reason_code="no_approved_supplier_on_allowlist",
                                  state_patch=({"fulfillment_alternatives": _alts} if _alts else None),
                                  tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
        return res, None
    # Advisory pre-send gate (deterministic; PRIOR to the human GATE 2) attached to the persisted draft so
    # the operator sees allow / needs_info / block before approving. Does not change the transition.
    draft_dict = draft.to_dict()
    draft_dict["send_gate"] = draft_send_gate(draft_dict)
    trace_for_selection = trace_id or (cur.source_trace_id if cur else None)
    _emit_supplier_selection_trace(trace_id=trace_for_selection, case_id=case_id, draft=draft, tenant_id=tenant_id)
    res = workflow.transition(
        db, case_id=case_id, event="external_message_drafted", actor=actor,
        reason_code="supplier_quote_drafted", confidence=draft.confidence,
        evidence={"content_hash": draft.content_hash, "recipient_domain": draft.recipient_domain,
                  "rationale": draft.rationale, "evidence_ids": [e["evidence_id"] for e in draft.evidence]},
        state_patch={"draft": draft_dict}, tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    return res, draft


def edit_draft(db, *, case_id: str, actor: Actor, subject: Optional[str] = None, body: Optional[str] = None,
               tenant_id: str = "default", now_iso: Optional[str] = None, trace_id: Optional[str] = None):
    """HUMAN edits the pending draft (subject/body) before approving. Recomputes the content_hash and
    fires external_message_drafted (AWAITING_APPROVAL → QUOTE_DRAFTED), which VOIDS any prior approval —
    the send gate will reject the stale hash. The claim-safety guard still applies, so a human edit
    cannot introduce a price/commitment leak or drop the not-a-PO footer. Returns (TransitionResult,
    draft-dict|None)."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    draft = dict((cur.state_json.get("draft") if cur else None) or {})
    if not draft:
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "no_draft",
                                         http_status=409), None
    new_subject = draft.get("subject", "") if subject is None else str(subject)
    new_body = draft.get("body", "") if body is None else str(body)
    if not _claim_safe(new_body, recipient_domain=draft.get("recipient_domain")):
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "unsafe_edit",
                                         http_status=409), None
    draft["subject"] = new_subject
    draft["body"] = new_body
    draft["content_hash"] = content_hash(new_subject, new_body)
    res = workflow.transition(
        db, case_id=case_id, event="external_message_drafted", actor=actor, reason_code="human_edited_draft",
        confidence=float(draft.get("confidence") or 0.9),
        evidence={"content_hash": draft["content_hash"], "edited_by": actor.id},
        state_patch={"draft": draft}, tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    return res, (draft if res.ok else None)


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


# ── RFI: human-fired supplier clarification (consumes a needs_info send-gate) ──
RFI_TEMPLATE: Dict[str, str] = {
    "subject": "Clarification request — {item_ref} — {case_ref}",
    "body": (
        "Hello {supplier_name},\n\n"
        "Before we proceed, could you please clarify the following:\n"
        "{question}\n\n"
        "This request does not constitute a purchase order.\n\n"
        "Regards,\nProcurement"
    ),
}


def request_supplier_info(db, *, case_id: str, actor: Actor, question: str, transport: Optional[Any] = None,
                          tenant_id: str = "default", now_iso: Optional[str] = None,
                          trace_id: Optional[str] = None):
    """HUMAN sends a scoped RFI (clarification) to the ALREADY-resolved supplier before approving the RFQ —
    the recoverable path for a ``needs_info`` send-gate. Same cage as the RFQ: recipient from the draft's
    allowlisted domain (never free text), claim-safe body (no price/PO leak), content_hash pinned, and
    actually TRANSMITTED through the transport seam (SANDBOX by default; SMTP at deploy) before the
    workflow transition fires (AWAITING_APPROVAL → AWAITING_SUPPLIER_INFO). A real transport failure
    records NO send and leaves the case unchanged. Returns (TransitionResult, rfi-dict|None)."""
    cur = workflow.repository.current_version(db, case_id, tenant_id)
    draft = (cur.state_json.get("draft") if cur else None) or {}
    domain = str(draft.get("recipient_domain") or "")
    if not domain:
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "no_recipient",
                                         http_status=409), None
    q = str(question or "").strip()
    if not q:
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "empty_question",
                                         http_status=400), None
    item_ref = str((draft.get("commercial_scope") or {}).get("item_ref") or "the requested item")
    supplier_name = _resolve_supplier_name(db, domain, tenant_id) or str(draft.get("recipient_ref") or "Supplier")
    subject = RFI_TEMPLATE["subject"].format(item_ref=item_ref, case_ref=case_id)
    body = RFI_TEMPLATE["body"].format(supplier_name=supplier_name, question=q)
    if not _claim_safe(body, recipient_domain=domain):  # a price/PO/URL/foreign-recipient leak is refused
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "unsafe_rfi",
                                         http_status=409), None
    chash = content_hash(subject, body)
    recipient = str(draft.get("recipient_email") or domain)
    # Transmit through the transport seam (mirrors send_approved). Sandbox returns a DEMO-OUT- ref.
    from src.app.services.fulfillment.transport import get_transport
    tx = transport or get_transport()
    sent = tx.send(to=recipient, subject=subject, body=body, idempotency_key=chash)
    if getattr(sent, "status", "failed") != "sent":
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "rfi_send_failed",
                                         http_status=502), None
    rfi = {"subject": subject, "body": body, "content_hash": chash, "recipient_domain": domain,
           "recipient_email": draft.get("recipient_email"), "recipient": recipient, "question": q,
           "provider_ref": sent.provider_ref, "status": "sent", "transport": getattr(sent, "detail", "")}
    res = workflow.transition(
        db, case_id=case_id, event="supplier_info_requested", actor=actor,
        reason_code="supplier_clarification_sent",
        evidence={"content_hash": chash, "recipient_domain": domain, "recipient": recipient,
                  "provider_ref": sent.provider_ref, "question": q},
        state_patch={"rfi": rfi}, tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    return res, (rfi if res.ok else None)


def record_supplier_info(db, *, case_id: str, actor: Actor, answer: str, tenant_id: str = "default",
                         now_iso: Optional[str] = None, trace_id: Optional[str] = None):
    """Record the supplier's clarification reply (AWAITING_SUPPLIER_INFO → AWAITING_APPROVAL) so the human
    can approve the RFQ with the answer on file. Returns (TransitionResult, rfi_response-dict|None)."""
    ans = str(answer or "").strip()
    if not ans:
        cur = workflow.repository.current_version(db, case_id, tenant_id)
        return workflow.TransitionResult(False, case_id, cur.state if cur else None, "empty_answer",
                                         http_status=400), None
    rfi_response = {"answer": ans}
    res = workflow.transition(
        db, case_id=case_id, event="supplier_info_received", actor=actor,
        reason_code="supplier_info_received", evidence={"answer_chars": len(ans)},
        state_patch={"rfi_response": rfi_response}, tenant_id=tenant_id, now_iso=now_iso, trace_id=trace_id)
    return res, (rfi_response if res.ok else None)
