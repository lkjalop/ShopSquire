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
    apply_derivations,
    defs_union,
    derivations_union,
    evaluate_requirements,
    extract_categoricals,
    extract_quantities,
    normalize_specs,
)
from src.app.services.catalog_read_model import VariantView
from src.app.services.recommendation_core.envelope import ProductCard

import logging
_log = logging.getLogger("shopsquire.recommendation_core.fit")

DEFAULT_VERTICALS = ("electronics", "pharmacy", "fashion")


def variant_attributes(view: VariantView,
                       defs: Optional[Dict[str, AttributeDef]] = None) -> Dict[str, Any]:
    """One variant's canonical attributes: normalized specs, backfilled by unit-anchored
    title extraction (specs win on conflict — structured data outranks marketing copy), then
    cross-key derivations (gpu_discrete=false ⇒ gpu_vram_gb=0 — fill-only-missing, so both the
    specs and the extraction still outrank a derived value)."""
    defs = defs or defs_union(DEFAULT_VERTICALS)
    attrs, _dropped = normalize_specs(view.specs or {}, defs)
    extracted, _ambiguous = extract_quantities(view.title or "", defs)
    for k, v in extracted.items():
        attrs.setdefault(k, v)
    # CAPABILITY signals from the title (form_factor / touchscreen / stylus) — makes the platform
    # SMART about drawing/creative/convertible intents against real products; specs still win.
    for k, v in extract_categoricals(view.title or "", defs).items():
        attrs.setdefault(k, v)
    apply_derivations(attrs, derivations_union(DEFAULT_VERTICALS), defs)
    return attrs


def _preferred_distance(attrs: Dict[str, Any], preferred: Dict[str, float]) -> float:
    """Nearness to the KB's RECOMMENDED values (review-9 #3): per key, relative distance capped
    at 1.0; an UNKNOWN attribute costs the full 1.0 (a product we can't verify never wins the
    preference tiebreak over one we can). 0.0 = spot-on every preferred value."""
    total = 0.0
    for k, p in preferred.items():
        try:
            pv = float(p)
        except (TypeError, ValueError):
            _log.debug("unusable preferred value for %s: %r", k, p)
            continue
        a = attrs.get(k)
        if isinstance(a, bool) or not isinstance(a, (int, float)):
            total += 1.0
        else:
            total += min(1.0, abs(float(a) - pv) / max(abs(pv), 1.0))
    return round(total, 4)


def build_cards(variants: List[VariantView],
                requirements: Optional[Dict[str, Any]] = None,
                *, defs: Optional[Dict[str, AttributeDef]] = None,
                limit: int = 10, sort: Optional[str] = None,
                preferred: Optional[Dict[str, float]] = None) -> Tuple[List[ProductCard], Dict[str, Any]]:
    """(ranked cards, fit_summary). With no requirements: price-ranked cards, no verdicts.
    With requirements: tri-state per variant, honest ordering, closest-match when dry.
    Requirements accept (op, thr) per key OR a predicate LIST [(op, thr), ...] (a RANGE —
    M2-B1); evaluate_requirements handles both. sort (R9.2, ranking.SORTS) applies the
    shopper's explicit price preference within fit-truth tiers. preferred (review-9 #3) is the
    KB's recommended values {key: value} — a SOFT nearness stage in the ranker, never a gate."""
    from src.app.services.recommendation_core.ranking import rank as _rank
    defs = defs or defs_union(DEFAULT_VERTICALS)
    # retrieval_order = the SKU order the evidence stage handed us (relevance signal for the
    # ranker's stage 4); the ranker owns ORDERING, this stage owns VERDICTS.
    retrieval_order = [v.sku for v in variants]
    built: List[ProductCard] = []
    pref_dist: Dict[str, float] = {}
    counts = {"meets": 0, "unknown": 0, "fails": 0}
    # capability floor (Phase 1a): the cheapest product in THIS candidate set that MEETS the
    # requirements — the honest "starts at $X for this capability", DERIVED from the real catalog,
    # never a stored number. Computed in the verdict pass (no extra iteration).
    floor_cents: Optional[int] = None
    for v in variants:
        attrs = variant_attributes(v, defs)
        if preferred:
            pref_dist[v.sku] = _preferred_distance(attrs, preferred)
        card = ProductCard(sku=v.sku, title=v.title, price_cents=v.price_cents,
                           currency=v.currency, brand=v.brand, image_url=v.image_url,
                           stock=v.stock, stock_source=v.stock_source)
        if requirements:
            verdict = evaluate_requirements(attrs, requirements)
            card.fit = verdict
            overall = verdict["overall"]
            counts[overall] += 1
            if overall == "meets" and v.price_cents is not None:
                floor_cents = v.price_cents if floor_cents is None else min(floor_cents, v.price_cents)
            failed = [k for k, val in verdict["per_key"].items() if val is False]
            if overall == "meets":
                card.why.append(f"meets all {len(requirements)} requirements")
            elif overall == "unknown":
                card.why.append("unverified: " + ", ".join(verdict["unknown_keys"]))
            else:
                card.why.append("below requirement: " + ", ".join(failed))
        built.append(card)
    cards = _rank(built, retrieval_order=retrieval_order, limit=limit, sort=sort,
                  preferred_dist=(pref_dist or None))
    def _describe(spec) -> str:
        preds = spec if isinstance(spec, list) else [spec]
        return " and ".join(f"{op} {thr}" for op, thr in preds)

    summary: Dict[str, Any] = {
        "requirements": {k: _describe(spec) for k, spec in (requirements or {}).items()},
        **counts,
        "capability_floor_cents": floor_cents,   # cheapest MEETS in this candidate set (Phase 1a)
        "closest_match_mode": bool(requirements) and counts["meets"] == 0 and bool(cards),
    }
    return cards, summary
