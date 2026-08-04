"""Competitive RFQ fan-out + quote comparison (agnostic CORE).

Phase 1 of multi-supplier procurement: instead of drafting to only the single top supplier, build a
FULLY-CAGED draft for each of the top-N approved suppliers (every draft goes through the exact same
claim-safety/evidence/gate machinery as the single-supplier path), and rank returned quotes by a
vertical-blind composite (price · lead time · reliability) so the operator can choose on the merits.

Bounded autonomy is preserved: this DRAFTS and COMPARES — it never sends. Each recipient is resolved
from the approved-supplier allowlist (draft.ranked_approved_suppliers), never from buyer input. The
actual send still goes one-at-a-time through the human GATE 2.

Vertical-blind: the comparator speaks only cents / days / reliability ratios — zero product vocabulary.
Never raises on a single bad draft/quote (best-effort: a failing supplier is skipped, not fatal).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from src.app.services.fulfillment.draft import (
    SupplierDraft,
    build_draft,
    draft_send_gate,
    ranked_approved_suppliers,
)

# default composite weights — lower price + shorter lead + higher reliability is better. Tunable per call.
_DEFAULT_WEIGHTS = {"price": 0.5, "lead_time": 0.25, "reliability": 0.25}


def build_rfq_fanout(
    db,
    *,
    item_ref: str,
    quantity: int,
    case_ref: str,
    top_n: int = 3,
    rank_fn: Optional[Callable] = None,
    allowlist_fn: Optional[Callable] = None,
    tenant_id: str = "default",
    **draft_kw: Any,
) -> List[SupplierDraft]:
    """Build a caged supplier draft for each of the top-N approved suppliers for ``item_ref``.

    Returns the list of drafts (one per qualifying supplier; an unsafe/failed draft is dropped). Every
    draft reuses build_draft's full cage, so price/PO/URL/foreign-recipient leakage is rejected per draft.
    """
    suppliers = ranked_approved_suppliers(
        db, item_ref=item_ref, top_n=top_n, rank_fn=rank_fn, allowlist_fn=allowlist_fn, tenant_id=tenant_id)
    drafts: List[SupplierDraft] = []
    for sup in suppliers:
        try:
            d = build_draft(db, item_ref=item_ref, quantity=quantity, case_ref=case_ref,
                            supplier_override=sup, tenant_id=tenant_id, **draft_kw)
        except Exception:
            d = None
        if d is not None:
            drafts.append(d)
    return drafts


def fanout_preview(drafts: List[SupplierDraft]) -> List[Dict[str, Any]]:
    """Operator-facing preview rows for a fan-out: recipient + subject/body + confidence + advisory send-gate.
    The send-gate is the same deterministic pre-send check shown on the single-supplier draft."""
    rows: List[Dict[str, Any]] = []
    for d in drafts:
        dd = d.to_dict()
        rows.append({
            "recipient_ref": dd.get("recipient_ref"),
            "recipient_domain": dd.get("recipient_domain"),
            "recipient_email": dd.get("recipient_email"),
            "subject": dd.get("subject"),
            "body": dd.get("body"),
            "confidence": dd.get("confidence"),
            "content_hash": dd.get("content_hash"),
            "send_gate": draft_send_gate(dd),
        })
    return rows


def _f(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def compare_quotes(quotes: List[Dict[str, Any]], *, weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Rank competing supplier quotes by a vertical-blind composite and recommend the best.

    Each quote: {supplier_ref?, recipient_domain?, unit_price_cents, lead_time_days?, reliability?,
    quantity?, valid_until?}. Scoring (each normalised to [0,1], higher = better):
      price       = cheapest_unit_price / this_unit_price        (weight 0.50)
      lead_time   = shortest_lead / this_lead                    (weight 0.25)
      reliability = reliability as given (0..1)                  (weight 0.25)
    A quote with no usable unit price is excluded (can't compete on price). Returns
    {ranked:[...], recommended:{...}|None, considered:int, excluded:int}. Never raises.
    """
    w = {**_DEFAULT_WEIGHTS, **(weights or {})}
    norm: List[Dict[str, Any]] = []
    excluded = 0
    for q in quotes or []:
        price = _f(q.get("unit_price_cents"))
        if price is None or price <= 0:
            excluded += 1
            continue
        lead = _f(q.get("lead_time_days"))
        rel = _f(q.get("reliability"))
        norm.append({
            "supplier_ref": q.get("supplier_ref"),
            "recipient_domain": q.get("recipient_domain"),
            "unit_price_cents": price,
            "lead_time_days": lead,
            "reliability": rel if rel is not None else None,
            "quantity": q.get("quantity"),
            "valid_until": q.get("valid_until"),
        })
    if not norm:
        return {"ranked": [], "recommended": None, "considered": 0, "excluded": excluded}

    cheapest = min(n["unit_price_cents"] for n in norm)
    leads = [n["lead_time_days"] for n in norm if n["lead_time_days"] is not None and n["lead_time_days"] > 0]
    shortest_lead = min(leads) if leads else None

    for n in norm:
        price_score = cheapest / n["unit_price_cents"]
        if shortest_lead is not None and n["lead_time_days"] and n["lead_time_days"] > 0:
            lead_score = shortest_lead / n["lead_time_days"]
        else:
            lead_score = 0.0 if shortest_lead is not None else 1.0  # no lead given → neutral when none have it
        rel_score = n["reliability"] if n["reliability"] is not None else 0.0
        composite = (w["price"] * price_score + w["lead_time"] * lead_score + w["reliability"] * rel_score)
        reasons = []
        if n["unit_price_cents"] == cheapest:
            reasons.append("lowest_unit_price")
        if shortest_lead is not None and n["lead_time_days"] == shortest_lead:
            reasons.append("shortest_lead_time")
        if n["reliability"] is not None and n["reliability"] >= 0.9:
            reasons.append("high_reliability")
        n["scores"] = {"price": round(price_score, 4), "lead_time": round(lead_score, 4),
                       "reliability": round(rel_score, 4)}
        n["composite"] = round(composite, 4)
        n["reasons"] = reasons

    # rank by composite desc; tie-break on lower price then shorter lead (deterministic)
    ranked = sorted(norm, key=lambda n: (-n["composite"], n["unit_price_cents"],
                                         n["lead_time_days"] if n["lead_time_days"] is not None else 1e9))
    return {"ranked": ranked, "recommended": ranked[0], "considered": len(ranked), "excluded": excluded}
