"""Fast-path catalog scoring + candidate assembly (agnostic CORE).

Extracted from the recommend fast path, which carried TWO drift hazards:
  1. the per-row candidate assembly (score → confidence → factors → score_norm) was duplicated
     verbatim in the live-catalog loop AND the profile-fallback loop — one shared builder now;
  2. the scorer hardcoded category words for one vertical. Now the category boost is
     QUERY-ANCHORED against the active profile's ``category_keywords`` groups: the item is
     boosted only when the buyer's query names a category group AND the item matches that same
     group — any vertical's vocabulary, zero of it in core.

Pure functions over row dicts; profile vocabulary comes from StoreProfile slots (the sanctioned
pattern). Budget-band truth stays in recommend_budget_band (single source). Never raises.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, List, Optional


def coerce_specs(raw_specs: Any) -> Dict[str, Any]:
    """Row specs may arrive as dict or JSON text; anything else is an empty dict."""
    if isinstance(raw_specs, dict):
        return raw_specs
    if isinstance(raw_specs, str) and raw_specs.strip():
        try:
            parsed = json.loads(raw_specs)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _cents_to_units(price_cents: int) -> float:
    try:
        return float(price_cents) / 100.0
    except (TypeError, ValueError):
        return 0.0


def _category_groups() -> Dict[str, List[str]]:
    try:
        from src.app.platform.store_profile import profile_slot
        raw = profile_slot("category_keywords", default={}) or {}
        return {str(k): [str(t).lower() for t in (v or [])] for k, v in raw.items()} if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _known_brands() -> Iterable[str]:
    try:
        from src.app.platform.store_profile import profile_slot
        return profile_slot("known_brands", default=()) or ()
    except Exception:
        return ()


def category_match_boost(haystack: str, query: str) -> float:
    """+30 when the query names a profile category group AND the item matches that SAME group.
    Query-anchored deliberately: a category-less query boosts nothing (the old form boosted one
    hardcoded category for every query — a single-vertical bias)."""
    q = str(query or "").lower()
    hs = str(haystack or "").lower()
    for _group, terms in _category_groups().items():
        if any(t and t in q for t in terms) and any(t and t in hs for t in terms):
            return 30.0
    return 0.0


def score_candidate(
    row: Dict[str, Any],
    query: str,
    *,
    safe_hints: Dict[str, Any],
    budget_min: Optional[int],
    budget_max: Optional[int],
    use_case_fit: Dict[str, Any],
) -> float:
    """The fast-path score: category match (query-anchored, profile groups) + adapter use-case
    fit + brand hints/profile brands + budget band (dominating over-budget penalty via
    recommend_budget_band) + stock nudge."""
    name = str(row.get("name") or "").lower()
    specs = row.get("specs") if isinstance(row.get("specs"), dict) else {}
    spec_text = json.dumps(specs, ensure_ascii=False).lower()
    haystack = f"{name} {spec_text}"
    q = str(query or "").lower()
    price_cents = int(row.get("price_cents") or 0)
    price = _cents_to_units(price_cents)

    score = category_match_boost(haystack, query)
    fit = use_case_fit or {}
    if fit.get("use_case"):
        if fit.get("meets"):
            score += 35.0
        else:
            score += 4.0
            if any(str(g).startswith("needs_discrete_gpu") for g in (fit.get("gaps") or [])):
                score -= 14.0
    elif fit.get("tier") in ("entry", "mid", "high"):
        score += 8.0
    adj = fit.get("score_adjustment")
    if adj:
        score += float(adj)
    for brand in safe_hints.get("brand_hints") or []:
        if brand and brand in haystack:
            score += 22.0
    for token in _known_brands():
        token = str(token).lower()
        if token and token in q and token in haystack:
            score += 12.0
    if budget_min is not None and price >= float(budget_min):
        score += 8.0
    if budget_max is not None and price <= float(budget_max):
        score += 10.0
    try:
        from src.app.services.recommend_budget_band import band_status, budget_rank_penalty
        score += budget_rank_penalty(band_status(price_cents, budget_min, budget_max))
    except Exception:
        if budget_max is not None and price > float(budget_max):
            score -= min(20.0, (price - float(budget_max)) / 100.0)
    try:
        if int(row.get("stock") or 0) > 0:
            score += 6.0
    except (TypeError, ValueError):
        pass
    return score


def build_candidate(
    item: Dict[str, Any],
    query: str,
    *,
    safe_hints: Dict[str, Any],
    budget_min: Optional[int],
    budget_max: Optional[int],
    use_case_fit_fn: Callable[[Dict[str, Any], str], Dict[str, Any]],
) -> Dict[str, Any]:
    """Stamp score / confidence / factors / score_norm onto one candidate row — the assembly that
    was previously copy-pasted between the live-catalog and fallback loops. Mutates + returns."""
    fit = use_case_fit_fn(item, query) or {}
    item["score"] = score_candidate(item, query, safe_hints=safe_hints,
                                    budget_min=budget_min, budget_max=budget_max, use_case_fit=fit)
    item["confidence"] = round(max(0.15, min(0.99, item["score"] / 100.0)), 6)
    price = _cents_to_units(item.get("price_cents") or 0)
    in_band = budget_max is not None and price <= float(budget_max)
    name_l = str(item.get("name") or "").lower()
    query_hit = any(tok in name_l for tok in str(query or "").lower().split())
    item["factors"] = {
        "positive": list(filter(None, [
            "price_fit" if in_band else ("query_match" if query_hit else "catalog_match"),
            "safe_image_brand_hint" if safe_hints.get("brand_hints") else None,
            *(fit.get("reasons") or []),
            "in_stock" if int(item.get("stock") or 0) > 0 else None,
        ]))[:4],
        "negative": list(fit.get("gaps") or [])[:2],
    }
    item["score_norm"] = round(max(1.0, min(99.0, item["score"])), 3)
    return item
