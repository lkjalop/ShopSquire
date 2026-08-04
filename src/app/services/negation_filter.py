"""Negation / exclusion response filter (agnostic core).

Drops products the shopper explicitly EXCLUDED ("a laptop but not Apple", "without a touchscreen",
"no refurbished") at the response chokepoint, so EVERY return branch (fast path + main path + early
returns) honours negation uniformly. The excluded TERM is matched against product DATA
(name/brand/sku/title/product_type) — there are NO hardcoded brand/vertical literals here, so the
mechanism is vertical-blind.

Fail-safe by construction:
  * a term that matches no product drops nothing (over-capture upstream is harmless);
  * an over-broad exclusion can NEVER blank the page — if applying it would remove every result,
    the originals are kept untouched (better to show too much than nothing).

Pure + defensive: no I/O, no LLM, never raises (worst case it returns the payload unchanged), and
NO silent `except: pass` — every branch is an explicit guard.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

_HAYSTACK_FIELDS = ("name", "brand", "sku", "title", "product_type")


def _haystack(p: Any) -> str:
    """Lowercased searchable text for one product (DATA only — no vertical assumptions)."""
    if not isinstance(p, dict):
        return ""
    return " ".join(str(p.get(k) or "") for k in _HAYSTACK_FIELDS).lower()


def _clean_terms(exclusions: Optional[List[str]]) -> List[str]:
    return [t for t in (str(x).strip().lower() for x in (exclusions or [])) if len(t) >= 2]


def _filter_list(items: Any, terms: List[str]) -> List[Any]:
    if not isinstance(items, list):
        return items
    return [p for p in items if not any(t in _haystack(p) for t in terms)]


def apply_negation_exclusions(payload: Dict[str, Any], exclusions: Optional[List[str]]) -> Dict[str, Any]:
    """Remove excluded products from ``payload['results']`` (and the mirrored ``products`` list).

    Applies ONLY when the exclusion removes SOME but not ALL results — so a no-op exclusion and an
    everything-matching exclusion both leave the page intact. Annotates the payload with what was
    removed for trace transparency. Never raises.
    """
    if not isinstance(payload, dict):
        return payload
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return payload
    terms = _clean_terms(exclusions)
    if not terms:
        return payload
    kept = _filter_list(results, terms)
    # Fail-safe: never blank the page. Only commit when the filter dropped at least one but left ≥1.
    if not kept or len(kept) == len(results):
        return payload
    payload["results"] = kept
    if isinstance(payload.get("products"), list):
        products_kept = _filter_list(payload["products"], terms)
        # Same fail-safe on the mirror list (keep originals if it would empty it).
        payload["products"] = products_kept if products_kept else payload["products"]
    payload["negation_excluded_count"] = len(results) - len(kept)
    payload["negation_excluded_terms"] = terms[:5]
    return payload
