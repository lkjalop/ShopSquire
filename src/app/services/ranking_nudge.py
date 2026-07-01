"""Reversible ranking nudge through the experiment gate (agnostic CORE).

The FIRST measured live adaptation: when a ranking experiment is LIVE and the user is in the TREATMENT
arm, products the hippograph recalls as high-reward for this context get a SMALL, BOUNDED, AUDITABLE
score boost, then the list is re-sorted. CONTROL users and non-live experiments are returned UNCHANGED
(identity — the same object). Reversible by construction:
  • the boost is an additive capped delta tagged on each row (`_nudge_delta`) → replayable / subtractable;
  • the experiment gate's REVERT decision flips the experiment off `live` → the nudge stops globally;
  • the enabling flag off stops it everywhere.
It never invents products and never boosts beyond the cap. Vertical-blind: operates on sku + score only.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

_NUDGE_TAG = "market-intel boost (experiment)"


def apply_experiment_nudge(
    results: List[Dict[str, Any]],
    *,
    recall_ids: Iterable[str],
    assignment: str,
    live: bool,
    max_boost: float = 0.05,
    max_nudged_items: int = 3,
) -> List[Dict[str, Any]]:
    """Boost recalled products for TREATMENT users in a LIVE experiment, else return ``results``
    unchanged (identity). TWO treatment caps bound the blast radius: ``max_boost`` (per-item delta
    magnitude) and ``max_nudged_items`` (how many products can be boosted at all), so a treatment can
    never reshuffle the whole list. Returns the SAME object when nothing is nudged, so callers can
    `is`-check."""
    if str(assignment) != "treatment" or not live:
        return results
    boost = {str(x) for x in (recall_ids or []) if str(x).strip()}
    rows = results or []
    if not boost or not rows:
        return results
    cap = max(0, int(max_nudged_items))
    out: List[Dict[str, Any]] = []
    changed = False
    nudged = 0
    for r in rows:
        if isinstance(r, dict) and str(r.get("sku")) in boost and nudged < cap:
            r2 = dict(r)
            base = float(r2.get("score") or r2.get("score_norm") or 0.0)
            r2["score"] = base + float(max_boost)
            r2["_nudge_delta"] = float(max_boost)
            why = list(r2.get("why") or [])
            if _NUDGE_TAG not in why:
                why.append(_NUDGE_TAG)
            r2["why"] = why[:5]
            out.append(r2)
            changed = True
            nudged += 1
        else:
            out.append(r)
    if not changed:
        return results
    out.sort(key=lambda x: -(float(x.get("score") or 0.0)) if isinstance(x, dict) else 0.0)
    return out


_SR_TAG = "market-intel (demand-aware)"


def apply_sales_response_nudge(
    results: List[Dict[str, Any]],
    *,
    bias_by_sku: Dict[str, str],
    max_delta: float = 0.04,
    max_nudged_items: int = 6,
) -> List[Dict[str, Any]]:
    """Demand-aware ranking nudge (M5 consume #2): each item's promotion_bias moves its score by a small,
    BOUNDED delta — PROMO_BOOST (surplus/hot) → +delta so it surfaces; PROMO_SUPPRESS (can't-ship shortage)
    → -delta so it recedes; anything else is left untouched. Two caps bound the blast radius (``max_delta``
    magnitude, ``max_nudged_items`` count) so it can never reshuffle the whole list. Reversible: the delta is
    tagged ``_sales_response_delta`` (subtractable by revert_nudge). Returns the SAME object when nothing is
    nudged (callers can `is`-check). Vertical-blind: sku + score + bias enum only."""
    bias = {str(k): str(v) for k, v in (bias_by_sku or {}).items()}
    rows = results or []
    if not bias or not rows:
        return results
    cap = max(0, int(max_nudged_items))
    out: List[Dict[str, Any]] = []
    changed = False
    nudged = 0
    for r in rows:
        b = bias.get(str(r.get("sku"))) if isinstance(r, dict) else None
        if b in ("boost", "suppress") and nudged < cap:
            r2 = dict(r)
            base = float(r2.get("score") or r2.get("score_norm") or 0.0)
            delta = float(max_delta) if b == "boost" else -float(max_delta)
            r2["score"] = base + delta
            r2["_sales_response_delta"] = delta
            why = list(r2.get("why") or [])
            tag = _SR_TAG + (" ↑" if b == "boost" else " ↓")
            if tag not in why:
                why.append(tag)
            r2["why"] = why[:5]
            out.append(r2)
            changed = True
            nudged += 1
        else:
            out.append(r)
    if not changed:
        return results
    out.sort(key=lambda x: -(float(x.get("score") or 0.0)) if isinstance(x, dict) else 0.0)
    return out


def revert_nudge(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Undo a nudge from a captured response (replay/audit): subtract each `_nudge_delta` and re-sort.
    Proves per-response reversibility — the boost leaves a complete trail."""
    rows = results or []
    if not any(isinstance(r, dict) and (r.get("_nudge_delta") or r.get("_sales_response_delta")) for r in rows):
        return results
    out = []
    for r in rows:
        if isinstance(r, dict) and (r.get("_nudge_delta") or r.get("_sales_response_delta")):
            r2 = dict(r)
            delta = float(r2.pop("_nudge_delta", 0.0) or 0.0) + float(r2.pop("_sales_response_delta", 0.0) or 0.0)
            r2["score"] = float(r2.get("score") or 0.0) - delta
            r2["why"] = [w for w in (r2.get("why") or []) if w != _NUDGE_TAG and not str(w).startswith(_SR_TAG)]
            out.append(r2)
        else:
            out.append(r)
    out.sort(key=lambda x: -(float(x.get("score") or 0.0)) if isinstance(x, dict) else 0.0)
    return out
