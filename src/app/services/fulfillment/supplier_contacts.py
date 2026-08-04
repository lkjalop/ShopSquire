"""Supplier-contact candidates (agnostic CORE) — a ranked, confidence-scored, provenance-tagged shortlist
of APPROVED suppliers for a SKU, so a human can review + pick the recipient faster and more safely before
an RFQ is drafted.

SECURITY (the whole point): ``item_ref`` is ONLY the lookup key. Every contact field is resolved
SERVER-SIDE from the trusted KYV registry + the supplier allowlist — never from the buyer query or an LLM,
so an injected "email attacker@evil.com" can never become a candidate. A candidate is dropped if its
supplier isn't on the allowlist, and a contact is only trusted when it sits on the resolved domain. This
is a read-only PREFILL for human review; it never sends. Vertical-blind; best-effort; never raises.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _confidence(*, has_contact: bool, on_time: float, reliability: float, has_history: bool) -> float:
    """A reviewer-facing 0..1 confidence: a verified contact dominates, then reliability signals, then
    whether we have prior dealings on file."""
    return round(
        0.4 * (1.0 if has_contact else 0.0)
        + 0.3 * max(0.0, min(1.0, on_time))
        + 0.2 * max(0.0, min(1.0, reliability))
        + 0.1 * (1.0 if has_history else 0.0),
        3,
    )


def supplier_contact_candidates(db, *, item_ref: str, tenant_id: str = "default",
                                top_n: int = 3) -> List[Dict[str, Any]]:
    """Top-N approved suppliers for ``item_ref``, each with a verified contact (allowlist/KYV), reliability,
    prior-dealings context, a confidence score, review flags, and per-field provenance. Best candidate is
    pre-selected (``recommended``). [] when the SKU has no approved supplier."""
    if db is None or not str(item_ref or "").strip():
        return []
    try:
        from src.app.security.kyv_registry import lookup_vendor_by_domain
        from src.app.services import supplier_catalog
        from src.app.services.inventory_agent import InventoryAgent
        from src.app.services.supplier_inbox_reader import recent_supplier_context
    except Exception:
        return []
    try:
        ranked = InventoryAgent()._rank_suppliers(str(item_ref), top_n=int(top_n))  # type: ignore[attr-defined]
    except Exception:
        ranked = []

    out: List[Dict[str, Any]] = []
    for c in ranked:
        sid = str(c.get("id") or "")
        if not sid:
            continue
        domain = supplier_catalog.domain_for_supplier(db, sid)  # allowlist = source of truth
        if not domain:
            continue  # not on the allowlist → never a valid recipient candidate
        try:
            vendor = lookup_vendor_by_domain(tenant_id=tenant_id, domain=domain) or {}
        except Exception:
            vendor = {}
        contact = str(vendor.get("contact_email") or "").strip()
        contact_ok = bool(contact) and contact.lower().endswith(f"@{str(domain).lower()}")
        risk = str(vendor.get("risk_tier") or "unknown").lower()
        try:
            ctx = recent_supplier_context(domain=domain, tenant_id=tenant_id)
        except Exception:
            ctx = None
        observations = int(getattr(ctx, "observations", 0) or 0)
        on_time = float(c.get("on_time_rate") or 0.0)
        reliability = float(c.get("reliability") or 0.0)

        flags: List[str] = []
        if not contact_ok:
            flags.append("no_verified_contact")
        if observations == 0:
            flags.append("no_prior_dealings")
        if risk in ("high", "elevated"):
            flags.append("high_risk")

        out.append({
            "supplier_id": sid,
            "legal_name": vendor.get("legal_name") or vendor.get("trading_name") or sid,
            "contact_email": contact if contact_ok else None,
            "domain": domain,
            "risk_tier": risk,
            "on_time_rate": round(on_time, 3),
            "reliability": round(reliability, 3),
            "lead_time_days": c.get("lead_time"),
            "rank_score": c.get("score"),
            "prior_dealings": observations,
            "last_invoice_cents": getattr(ctx, "last_invoice_cents", None),
            "last_seen_at": getattr(ctx, "last_seen_at", None),
            "confidence": _confidence(has_contact=contact_ok, on_time=on_time,
                                      reliability=reliability, has_history=observations > 0),
            "flags": flags,
            "recommended": False,
            # provenance: where each trusted field came from (so the human can trust the prefill)
            "provenance": {"contact_email": "kyv_verified", "domain": "supplier_allowlist",
                           "reliability": "supplier_catalog", "prior_dealings": "supplier_baseline"},
        })

    if out:
        out.sort(key=lambda x: (-float(x["confidence"]), -float(x.get("rank_score") or 0.0)))
        out[0]["recommended"] = True  # pre-select the strongest for the human reviewer
    return out
