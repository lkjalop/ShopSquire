"""Unified use-case registry (Track E consolidation) — ONE data-driven source per vertical.

Replaces the four drifting KB files with `data/use_cases/{vertical}.json` in the HYBRID namespace:
a COARSE use-case (`gaming`) carries a `baseline` spec + `budget_floor`, and optional fine
`variants` (`competitive`, `aaa_heavy`, …) that OVERRIDE the baseline (DRY). Mirrors
attribute_registry: vertical-blind mechanism, all knowledge in data, zero code per vertical.

STRANGLER: this is ADDITIVE. It stands beside the legacy KB files; consumers migrate onto
`resolve()` incrementally, then the legacy files are deleted. Nothing here changes what the
current recommender reads yet, so it does not perturb the V2 soak baseline.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("shopsquire.use_case_registry")

_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "use_cases"


@lru_cache(maxsize=16)
def load_use_cases(vertical: str) -> Dict[str, Any]:
    """The raw registry for one vertical, or {} when the file is absent (an un-scaffolded
    vertical resolves nothing rather than guessing)."""
    path = _DATA_DIR / f"{str(vertical).strip().lower()}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("use-case registry unreadable for %s: %s", vertical, exc)
        return {}


_VERTICALS = ("electronics", "home", "appliances", "furniture")


def list_use_cases(vertical: str) -> List[str]:
    return sorted((load_use_cases(vertical).get("use_cases") or {}).keys())


@lru_cache(maxsize=1)
def all_use_case_keys() -> frozenset:
    """Every use-case key across the populated verticals — the vocabulary the router adds to its
    closed use-case list so a smart intent ('drawing', 'creative') is classifiable at all. Cached;
    the scaffolded verticals contribute nothing until their JSON gains use_cases."""
    keys: set = set()
    for v in _VERTICALS:
        keys.update(list_use_cases(v))
    return frozenset(keys)


def list_variants(vertical: str, coarse: str) -> List[str]:
    uc = (load_use_cases(vertical).get("use_cases") or {}).get(str(coarse)) or {}
    return sorted((uc.get("variants") or {}).keys())


def variant_vocabulary(use_cases: Optional[List[str]] = None) -> Dict[str, List[str]]:
    """Closed variant vocabulary across installed vertical registries.

    The router may not know the final taxonomy node before classification, so it receives the
    union of real data-owned variants. Duplicate use-case keys are merged; invented values remain
    impossible because the selected value is clamped again against the resolved vertical.
    """
    wanted = set(use_cases or [])
    out: Dict[str, set[str]] = {}
    for vertical in _VERTICALS:
        for use_case in list_use_cases(vertical):
            if wanted and use_case not in wanted:
                continue
            variants = list_variants(vertical, use_case)
            if variants:
                out.setdefault(use_case, set()).update(variants)
    return {key: sorted(values) for key, values in sorted(out.items())}


def routing_guide(use_cases: Optional[List[str]] = None) -> Dict[str, str]:
    """Compact data-owned meanings for semantically adjacent use-case keys."""
    wanted = set(use_cases or [])
    out: Dict[str, str] = {}
    for vertical in _VERTICALS:
        rows = load_use_cases(vertical).get("use_cases") or {}
        for key, row in rows.items():
            if wanted and key not in wanted:
                continue
            description = str((row or {}).get("description") or "").strip()
            if description:
                out.setdefault(key, description)
    return dict(sorted(out.items()))


def variant_routing_guide(use_cases: Optional[List[str]] = None) -> Dict[str, Dict[str, str]]:
    """Variant names plus compact data-owned evidence phrases for model classification."""
    wanted = set(use_cases or [])
    out: Dict[str, Dict[str, str]] = {}
    for vertical in _VERTICALS:
        rows = load_use_cases(vertical).get("use_cases") or {}
        for key, row in rows.items():
            if wanted and key not in wanted:
                continue
            variants = (row or {}).get("variants") or {}
            for variant, detail in variants.items():
                keywords = [str(value).strip() for value in (detail or {}).get("keywords") or []
                            if str(value).strip()]
                out.setdefault(key, {})[variant] = " | ".join(keywords[:5])
    return {key: dict(sorted(values.items())) for key, values in sorted(out.items())}


def apply_use_case_exclusions(use_cases: List[str]) -> List[str]:
    """Apply registry-declared semantic exclusions while preserving model order."""
    selected = list(dict.fromkeys(use_cases))
    excluded: set[str] = set()
    for vertical in _VERTICALS:
        rows = load_use_cases(vertical).get("use_cases") or {}
        for key in selected:
            for value in (rows.get(key) or {}).get("excludes") or []:
                excluded.add(str(value))
    return [key for key in selected if key not in excluded]


def resolve(vertical: str, coarse: str, variant: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """A coarse use-case (+ optional variant) → merged CAPABILITY REQUIREMENTS, or None when the
    coarse key is unknown. Merge: variant requirements ADD/OVERRIDE the baseline (per-attribute);
    budget_band_hint is the variant's if present else the coarse hint. The `requirements` are the
    knowledge; the PRICE is not here — call derive_price_floor() to ground it in the catalog."""
    uc = (load_use_cases(vertical).get("use_cases") or {}).get(str(coarse))
    if not isinstance(uc, dict):
        return None
    reqs: Dict[str, Any] = dict(uc.get("requirements") or {})
    band = uc.get("budget_band_hint")
    resolved_variant = None
    vmap = uc.get("variants") or {}
    if variant and str(variant) in vmap:
        resolved_variant = str(variant)
        v = vmap[resolved_variant] or {}
        for k, pred in (v.get("requirements") or {}).items():
            reqs[k] = pred                                 # variant tightens/overrides per-attribute
        if v.get("budget_band_hint") is not None:
            band = v["budget_band_hint"]
    out: Dict[str, Any] = {
        "vertical": str(vertical), "use_case": str(coarse), "variant": resolved_variant,
        "label": uc.get("label"), "requirements": reqs, "budget_band_hint": band,
        "host_nodes": uc.get("host_nodes") or (load_use_cases(vertical).get("host_nodes") or []),
        "keywords": uc.get("keywords") or [],
    }
    if uc.get("content_advisory"):
        out["content_advisory"] = uc["content_advisory"]
    return out


def derive_price_floor(vertical: str, coarse: str, variant: Optional[str],
                       candidates: List[Any], *, defs: Optional[Dict[str, Any]] = None) -> Optional[int]:
    """The SMART floor (not a stored number): the CHEAPEST price_cents among `candidates`
    (VariantViews from the routed catalog node) that MEETS the use-case's capability requirements.
    None when nothing in stock meets them — honest ('we can't quote a floor for a capability we
    don't carry'), never a hardcoded guess. Self-correcting: it tracks real prices, and a shopper's
    brand/form preference (filtered candidates) escalates it naturally (a Mac-only set floors at the
    Mac price — no hardcoded premium)."""
    r = resolve(vertical, coarse, variant)
    reqs = (r or {}).get("requirements") or {}
    if not reqs or not candidates:
        return None
    from src.app.services.attribute_registry import defs_union, evaluate_requirements
    from src.app.services.recommendation_core.fit import variant_attributes
    defs = defs or defs_union((vertical,))
    pred = {k: (v[0], v[1]) for k, v in reqs.items() if isinstance(v, (list, tuple)) and len(v) == 2}
    floor: Optional[int] = None
    for c in candidates:
        price = getattr(c, "price_cents", None)
        if price is None:
            continue
        attrs = variant_attributes(c, defs)
        if evaluate_requirements(attrs, pred).get("overall") == "meets":
            floor = int(price) if floor is None else min(floor, int(price))
    return floor


def complements(vertical: str, coarse: str) -> List[Dict[str, Any]]:
    """The complementary products a use-case pairs with (Phase 1d.4) — e.g. drawing → a graphics
    tablet for pen input. Each declares {key, node (taxonomy handle to stock-check), label, reason,
    tags}. ONE declaration drives two behaviours downstream: bundle-upsell if the node is stocked,
    source-it (supplier RFQ) if not — stock truth picks the branch."""
    uc = (load_use_cases(vertical).get("use_cases") or {}).get(str(coarse)) or {}
    out = uc.get("complements")
    return out if isinstance(out, list) else []


def content_advisory(vertical: str, coarse: str) -> Optional[Dict[str, Any]]:
    """The advisory (if any) for a coarse use-case — e.g. a minor persona requesting mature-rated
    game specs. ADVISORY: the caller surfaces a clarification, never a hard block."""
    uc = (load_use_cases(vertical).get("use_cases") or {}).get(str(coarse)) or {}
    return uc.get("content_advisory")
