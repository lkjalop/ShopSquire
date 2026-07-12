"""Lexicographic ranking (V2 — GPT-5.6 review-2 ranking decision).

NOT the legacy ranker (imports v1's scoring assumptions) and NOT price-only within a fit group
(what fit.py did). A transparent lexicographic order where each stage only breaks ties the
prior stage left — so every position is explainable and no single learned score can override
a hard truth (a cheaper OUT-OF-STOCK item never outranks an in-stock match).

Stages, most-significant first:
  1. fit group          — meets(0) < unknown(1) < fails(2); no-requirements turns are all 0.
  2. fewest failed keys  — within 'fails', closest-to-meeting first.
  3. availability        — in-stock(0) < unknown-stock(1) < out-of-stock(2).
  4. retrieval relevance — position the evidence stage returned it (0 = most relevant); the
                           model/taxonomy/embedding order, preserved as a signal not a verdict.
  5. value               — price ascending (cheaper is better value, budget already applied
                           upstream); missing price sinks.
  6. stable SKU          — deterministic final tie-break (identical inputs → identical order,
                           which is what makes the shadow differ trustworthy).

Legacy factors (cross-encoder score, persona affinity, recency) become STAGE-5 FEATURES over
time; legacy ORDERING is not the target. Top-3 exact parity is a DIAGNOSTIC, not a gate.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from src.app.services.recommendation_core.envelope import ProductCard

_FIT_GROUP = {"meets": 0, "unknown": 1, "fails": 2}


def _availability_rank(card: ProductCard) -> int:
    if card.stock is None:
        return 1                     # unknown stock: neutral, between in-stock and OOS
    return 0 if card.stock > 0 else 2


SORTS = ("price_asc", "price_desc")   # closed refinement-sort vocabulary (R9.2)


def rank_key(card: ProductCard, *, relevance_rank: int = 0, sort: Optional[str] = None):
    """The lexicographic sort key. Pure; identical inputs → identical key.
    R9.2: an explicit shopper sort ('show me cheaper ones') promotes PRICE above retrieval
    relevance — never above fit/availability truth: a failing cheap unit still ranks below
    a meeting pricier one (stages 1-3 stay supreme)."""
    fit = card.fit or {}
    group = _FIT_GROUP.get(str(fit.get("overall") or "unknown"), 1) if card.fit else 0
    failed = sum(1 for v in (fit.get("per_key") or {}).values() if v is False)
    price = card.price_cents if card.price_cents is not None else 10**12  # missing price sinks
    if sort in SORTS:
        pkey = price if sort == "price_asc" else (
            -card.price_cents if card.price_cents is not None else 10**12)  # missing sinks both ways
        return (group, failed, _availability_rank(card), pkey, relevance_rank, card.sku)
    return (group, failed, _availability_rank(card), relevance_rank, price, card.sku)


def rank(cards: List[ProductCard], *, retrieval_order: Optional[List[str]] = None,
         limit: Optional[int] = None, sort: Optional[str] = None) -> List[ProductCard]:
    """Order cards lexicographically. retrieval_order is the SKU order the evidence stage
    returned (relevance signal); absent → relevance is neutral and other stages decide.
    sort ∈ SORTS applies the shopper's explicit price preference (see rank_key)."""
    rel: Dict[str, int] = {sku: i for i, sku in enumerate(retrieval_order or [])}
    default_rel = len(rel)   # SKUs not in the retrieval order sort after those that are
    ordered = sorted(cards, key=lambda c: rank_key(c, relevance_rank=rel.get(c.sku, default_rel),
                                                   sort=sort))
    return ordered[: max(1, int(limit))] if limit else ordered
