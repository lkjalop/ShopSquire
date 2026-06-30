"""Budget-band ranking truth (agnostic CORE).

Single source of truth for "is this price in the buyer's budget" + the ranking consequence. The catalog
DB query already hard-excludes out-of-band products when a budget is parsed; this module is the
DEFENSE-IN-DEPTH for the cases that slip past it — the under-review tolerance widening, the rerank path,
or a stretch item deliberately kept to avoid an empty result. The over-budget penalty is DOMINATING
(-1000) so no use-case / brand score can lift an over-budget unit above an in-budget one (the trust bug:
a $4,500 laptop ranked above in-budget units for a "$1,900 each" query).

Vertical-blind: pure cents/ratio math, no product vocabulary. Never raises.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.app.services.price_conversion import cents_to_dollars

# tolerances: a price up to 10% over the ceiling is a "stretch" (shown, demoted); beyond is "over".
_OVER_TOL = 0.10
# a price below 40% of the floor is "under" (likely the wrong tier); mild demotion.
_UNDER_TOL = 0.40

_PENALTY = {"in": 0.0, "stretch": -8.0, "over": -1000.0, "under": -6.0, "unknown": 0.0}


def band_status(price_cents: Optional[int], budget_min: Optional[float], budget_max: Optional[float],
                *, over_tol: float = _OVER_TOL, under_tol: float = _UNDER_TOL) -> str:
    """Classify a price against the budget: 'in' | 'stretch' | 'over' | 'under' | 'unknown'.
    budget_* are in DOLLARS (the constraint shape); price is in CENTS (the product shape)."""
    try:
        if not isinstance(price_cents, (int, float)) or price_cents <= 0:
            return "unknown"
        price = cents_to_dollars(price_cents)
        if budget_max is not None:
            bmax = float(budget_max)
            if price > bmax * (1.0 + over_tol):
                return "over"
            if price > bmax:
                return "stretch"
        if budget_min is not None:
            bmin = float(budget_min)
            if price < bmin * (1.0 - under_tol):
                return "under"
        return "in"
    except Exception:
        return "unknown"


def budget_rank_penalty(status: str) -> float:
    """The additive ranking delta for a band status. Over-budget is DOMINATING so it can never outrank
    an in-budget unit regardless of use-case/brand score."""
    return _PENALTY.get(str(status), 0.0)


def filter_to_band(candidates: List[Dict[str, Any]], budget_min: Optional[float], budget_max: Optional[float],
                   *, min_keep: int = 4, price_key: str = "price_cents") -> List[Dict[str, Any]]:
    """Keep in/stretch/under candidates; drop 'over'. If that leaves fewer than min_keep, re-add the
    cheapest 'over' ones tagged status='stretch' so the result is NEVER empty (the buyer always sees
    options, but over-budget is clearly marked and demoted by the penalty). Tags each kept item with
    ``budget_fit``. Stable: preserves input order for kept items."""
    if not candidates:
        return candidates
    kept, over = [], []
    for c in candidates:
        st = band_status(c.get(price_key), budget_min, budget_max)
        c = dict(c)
        c["budget_fit"] = st
        (over if st == "over" else kept).append(c)
    if len(kept) >= min_keep or not over:
        return kept
    over.sort(key=lambda c: float(c.get(price_key) or 0) or 1e18)
    for c in over[: max(0, min_keep - len(kept))]:
        c = dict(c)
        c["budget_fit"] = "stretch"  # surfaced but marked — never silently sold as in-budget
        kept.append(c)
    return kept
