"""Fit stage (V2 Phase 4, step 2) — normalized attributes → tri-state verdicts → honest ranking.

This is what RETIRES the legacy workload parsers: requirements arrive as canonical
{key: (op, threshold)} (from Steam floors, AI floors, or the plan stage), variants arrive as
VariantViews, and everything in between is the attribute registry — no regex over prose,
no spec parsing at decision time.

Honesty rules:
  • unknown ≠ fail: a variant missing vram data is UNKNOWN on a vram requirement — shown,
    labeled, never silently dropped (dropping unknowns is how thin catalogs zero out).
  • nothing meets → CLOSEST-MATCH mode, never an empty grid: rank by fewest failures and
    say so (the valorant known_wrong's structural fix, paired with the envelope's
    never-empty message).
  • Ranking is deterministic: meets < unknown < fails, then fewest failed keys, then price.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from src.app.services.attribute_registry import (
    AttributeDef,
    defs_union,
    evaluate_requirements,
    extract_quantities,
    normalize_specs,
)
from src.app.services.catalog_read_model import VariantView
from src.app.services.recommendation_core.envelope import ProductCard

DEFAULT_VERTICALS = ("electronics", "pharmacy", "fashion")


def variant_attributes(view: VariantView,
                       defs: Optional[Dict[str, AttributeDef]] = None) -> Dict[str, Any]:
    """One variant's canonical attributes: normalized specs, backfilled by unit-anchored
    title extraction (specs win on conflict — structured data outranks marketing copy)."""
    defs = defs or defs_union(DEFAULT_VERTICALS)
    attrs, _dropped = normalize_specs(view.specs or {}, defs)
    extracted, _ambiguous = extract_quantities(view.title or "", defs)
    for k, v in extracted.items():
        attrs.setdefault(k, v)
    return attrs


def build_cards(variants: List[VariantView],
                requirements: Optional[Dict[str, Tuple[str, Any]]] = None,
                *, defs: Optional[Dict[str, AttributeDef]] = None,
                limit: int = 10) -> Tuple[List[ProductCard], Dict[str, Any]]:
    """(ranked cards, fit_summary). With no requirements: price-ranked cards, no verdicts.
    With requirements: tri-state per variant, honest ordering, closest-match when dry."""
    from src.app.services.recommendation_core.ranking import rank as _rank
    defs = defs or defs_union(DEFAULT_VERTICALS)
    # retrieval_order = the SKU order the evidence stage handed us (relevance signal for the
    # ranker's stage 4); the ranker owns ORDERING, this stage owns VERDICTS.
    retrieval_order = [v.sku for v in variants]
    built: List[ProductCard] = []
    counts = {"meets": 0, "unknown": 0, "fails": 0}
    for v in variants:
        attrs = variant_attributes(v, defs)
        card = ProductCard(sku=v.sku, title=v.title, price_cents=v.price_cents,
                           currency=v.currency, brand=v.brand, image_url=v.image_url,
                           stock=v.stock, stock_source=v.stock_source)
        if requirements:
            verdict = evaluate_requirements(attrs, requirements)
            card.fit = verdict
            overall = verdict["overall"]
            counts[overall] += 1
            failed = [k for k, val in verdict["per_key"].items() if val is False]
            if overall == "meets":
                card.why.append(f"meets all {len(requirements)} requirements")
            elif overall == "unknown":
                card.why.append("unverified: " + ", ".join(verdict["unknown_keys"]))
            else:
                card.why.append("below requirement: " + ", ".join(failed))
        built.append(card)
    cards = _rank(built, retrieval_order=retrieval_order, limit=limit)
    summary: Dict[str, Any] = {
        "requirements": {k: f"{op} {thr}" for k, (op, thr) in (requirements or {}).items()},
        **counts,
        "closest_match_mode": bool(requirements) and counts["meets"] == 0 and bool(cards),
    }
    return cards, summary
