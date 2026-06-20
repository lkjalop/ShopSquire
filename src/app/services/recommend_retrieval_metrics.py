"""Retrieval parity metrics (Tier 2).

Measures the shadow hybrid pipeline (RECOMMEND_PIPELINE_V2: DB + vector + caption RRF) against the
PRIMARY (monolith) results — before any cutover. Pure functions, no I/O. The doc's rule: prove the
hybrid path is at least as good (overlap, budget adherence, latency) BEFORE flipping it to primary.

CORE / vertical-blind.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def skus_of(items: List[Dict[str, Any]] | None) -> List[str]:
    out: List[str] = []
    for it in items or []:
        if isinstance(it, dict):
            s = str(it.get("sku") or "").strip()
            if s:
                out.append(s)
    return out


def overlap_at_k(a: List[str], b: List[str], k: int = 5) -> float:
    """Jaccard overlap of the top-k of two ranked sku lists. 1.0 if both empty, 0.0 if one empty."""
    sa, sb = set(a[:k]), set(b[:k])
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return round(len(sa & sb) / len(sa | sb), 4)


def in_budget_fraction(
    items: List[Dict[str, Any]] | None, budget_min: Optional[float], budget_max: Optional[float]
) -> Optional[float]:
    """Fraction of items whose price respects the budget window. None if no priced items."""
    prices: List[float] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        p = it.get("price")
        if p is None:
            p = it.get("price_usd")
        try:
            prices.append(float(p))
        except (TypeError, ValueError):
            pass
    if not prices:
        return None

    def ok(p: float) -> bool:
        return (budget_min is None or p >= float(budget_min)) and (budget_max is None or p <= float(budget_max))

    return round(sum(1 for p in prices if ok(p)) / len(prices), 4)


def compute_parity(
    *,
    shadow_skus: List[str],
    primary_items: List[Dict[str, Any]] | None,
    shadow_count: int,
    shadow_latency_ms: int,
    budget_min: Optional[float] = None,
    budget_max: Optional[float] = None,
    k: int = 5,
) -> Dict[str, Any]:
    """Parity record for one request. shadow_skus = top ranked skus from the hybrid pipeline;
    primary_items = the monolith result dicts that were actually served."""
    primary_skus = skus_of(primary_items)
    return {
        "overlap_at_k": overlap_at_k(shadow_skus, primary_skus, k),
        "k": k,
        "shadow_count": int(shadow_count),
        "primary_count": len(primary_skus),
        "primary_in_budget": in_budget_fraction(primary_items, budget_min, budget_max),
        "shadow_latency_ms": int(shadow_latency_ms),
        "shadow_top_skus": list(shadow_skus[:k]),
        "primary_top_skus": primary_skus[:k],
    }
