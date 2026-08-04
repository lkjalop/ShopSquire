"""Product category detection and NQE template routing — VERTICAL-BLIND CORE.

Given a user query (and optional image labels), detects the product
category (e.g., laptop, phone, clothing, kitchen, furniture) and
returns the appropriate NQE template bank key for the template store.

This module carries NO flavour. The category/brand/use-case/spec patterns and the
image-label map are resolved PER REQUEST from the active StoreProfile (cached by
profile id, like store_profile). An electronics tenant gets electronics patterns
(config/store_profiles/electronics.json `entity_*` slots); a fashion/pharmacy tenant
derives its patterns from its own manufacturers / use_case_patterns / product_type_rules
via the accessor fallbacks — so a non-electronics request is NEVER scored against
electronics brands or use-cases.
"""
from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple


# ── Per-request (active-vertical) pattern resolution ─────────────────────────────
# Each accessor reads the active profile's explicit `entity_*` slot if present, else
# derives an equivalent from the profile's existing data (so non-electronics verticals
# work without hand-authored entity slots). Cached by resolved profile id.

@lru_cache(maxsize=8)
def _compiled_category_patterns_for(pid: str) -> List[Tuple[str, List[re.Pattern]]]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("entity_category_patterns", profile_id=pid, default=None)
    if isinstance(raw, list) and raw:
        return [(slug, [re.compile(p, re.IGNORECASE) for p in pats]) for slug, pats in raw]
    # Fallback: derive from product_type_rules (type -> its single pattern).
    rules = profile_slot("product_type_rules", profile_id=pid, default=None) or []
    out: List[Tuple[str, List[re.Pattern]]] = []
    for r in rules:
        t = (r or {}).get("type")
        pat = (r or {}).get("pattern")
        if t and pat:
            out.append((str(t), [re.compile(pat, re.IGNORECASE)]))
    return out


@lru_cache(maxsize=8)
def _image_label_map_for(pid: str) -> Dict[str, str]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("entity_image_label_map", profile_id=pid, default=None)
    return dict(raw) if isinstance(raw, dict) else {}


@lru_cache(maxsize=8)
def _brand_patterns_for(pid: str) -> List[Tuple[str, re.Pattern]]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("entity_brand_patterns", profile_id=pid, default=None)
    if isinstance(raw, dict) and raw:
        return [(b, re.compile(p, re.IGNORECASE)) for b, p in raw.items()]
    # Fallback: derive from manufacturers (name + aliases + product lines).
    mans = profile_slot("manufacturers", profile_id=pid, default=None) or {}
    out: List[Tuple[str, re.Pattern]] = []
    for name, spec in mans.items():
        toks = [name] + list((spec or {}).get("aliases") or []) + list((spec or {}).get("lines") or [])
        toks = [re.escape(str(t)) for t in toks if t]
        if toks:
            out.append((str(name), re.compile(r"\b(" + "|".join(toks) + r")\b", re.IGNORECASE)))
    return out


@lru_cache(maxsize=8)
def _use_case_patterns_for(pid: str) -> List[Tuple[str, re.Pattern]]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("entity_use_case_patterns", profile_id=pid, default=None)
    if isinstance(raw, dict) and raw:
        return [(uc, re.compile(p, re.IGNORECASE)) for uc, p in raw.items()]
    # Fallback: derive from the profile's use_case_patterns slot.
    ucp = profile_slot("use_case_patterns", profile_id=pid, default=None) or {}
    return [(uc, re.compile(p, re.IGNORECASE)) for uc, p in ucp.items()]


@lru_cache(maxsize=8)
def _spec_patterns_for(pid: str) -> List[Tuple[str, str, re.Pattern]]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("entity_spec_patterns", profile_id=pid, default=None)
    if isinstance(raw, list) and raw:
        return [(n, u, re.compile(p, re.IGNORECASE)) for n, u, p in raw]
    return []


@lru_cache(maxsize=8)
def _category_preference_for(pid: str) -> List[str]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("entity_category_preference", profile_id=pid, default=None)
    return [str(x) for x in raw] if isinstance(raw, list) else []


@lru_cache(maxsize=8)
def _template_banks_for(pid: str) -> frozenset:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("entity_template_banks", profile_id=pid, default=None)
    return frozenset(str(x) for x in raw) if isinstance(raw, list) else frozenset()


def _active_pid() -> str:
    from src.app.platform.store_profile import active_profile_id
    return active_profile_id()


def reset_cache() -> None:
    """Clear the per-profile pattern caches (test isolation / profile reload)."""
    for fn in (
        _compiled_category_patterns_for,
        _image_label_map_for,
        _brand_patterns_for,
        _use_case_patterns_for,
        _spec_patterns_for,
        _category_preference_for,
        _template_banks_for,
    ):
        try:
            fn.cache_clear()
        except Exception:
            pass


def category_from_image_labels(image_labels: List[str] | None = None) -> str | None:
    label_map = _image_label_map_for(_active_pid())
    counts: Counter[str] = Counter()
    for label in (image_labels or []):
        lbl = str(label or "").lower().strip()
        # Exact-match lookup first
        mapped = label_map.get(lbl)
        if mapped:
            counts[mapped] += 1
            continue
        # Multi-word label: check if any individual word is a known exact key
        words = lbl.replace("-", " ").split()
        for word in words:
            word_mapped = label_map.get(word)
            if word_mapped:
                counts[word_mapped] += 1
                break
    if not counts:
        return None
    ranked = counts.most_common()
    top_count = ranked[0][1]
    top_categories = [cat for cat, n in ranked if n == top_count]
    if len(top_categories) == 1:
        return top_categories[0]
    for preferred in _category_preference_for(_active_pid()):
        if preferred in top_categories:
            return preferred
    return top_categories[0]


# Routing / intent tokens that should NOT be treated as product categories
_ROUTING_INTENTS: frozenset[str] = frozenset({
    "", "unknown", "other", "visual_search", "cv_triage", "shopping",
    "support_claim", "intent", "general",
})


def detect_category(
    query: str | None = None,
    image_labels: List[str] | None = None,
    constraints: Dict[str, Any] | None = None,
) -> str:
    """Return the detected product category slug (primary/top category).

    Priority: explicit constraint > query text > image labels > "general".
    """
    # 1. Explicit constraint — but skip routing/intent strings
    if constraints:
        pt = str(constraints.get("product_type") or "").strip().lower()
        if pt and pt not in _ROUTING_INTENTS:
            return pt

    # 2. Query text matching
    text = (query or "").lower()
    if text:
        for cat, patterns in _compiled_category_patterns_for(_active_pid()):
            for p in patterns:
                if p.search(text):
                    return cat

    # 3. Image labels
    from_labels = category_from_image_labels(image_labels)
    if from_labels:
        return from_labels

    return "general"


def nqe_template_key(category: str) -> str:
    """Map a category slug to the NQE template bank key in config/.

    Returns the key used to look up templates in the TemplateStore
    (e.g. "default" for laptop, "clothing" for clothing).
    """
    # Categories with dedicated template banks (profile-defined)
    if category in _template_banks_for(_active_pid()):
        return category
    # Everything else falls back to default bank
    return "default"


def route(
    query: str | None = None,
    image_labels: List[str] | None = None,
    constraints: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """Convenience: detect + resolve template key in one call."""
    cat = detect_category(query, image_labels, constraints)
    return {"category": cat, "template_key": nqe_template_key(cat)}


# ── Multi-Category NER ───────────────────────────────────────────


def detect_entities(
    query: str | None = None,
    image_labels: List[str] | None = None,
    constraints: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Multi-category NER: extract all product categories, brands, specs, and use-cases.

    Returns:
        {
            "categories": [{"slug": "laptop", "confidence": 0.9}, ...],
            "brands": ["apple", "dell"],
            "use_cases": ["gaming", "programming"],
            "specs": {"ram": {"value": "16", "unit": "gb"}, ...},
            "primary_category": "laptop",
        }
    """
    pid = _active_pid()
    text = (query or "").lower()
    categories: List[Dict[str, Any]] = []
    brands: List[str] = []
    use_cases: List[str] = []
    specs: Dict[str, Dict[str, str]] = {}

    # Detect all matching categories from text
    if text:
        for cat, patterns in _compiled_category_patterns_for(pid):
            match_count = sum(1 for p in patterns if p.search(text))
            if match_count > 0:
                confidence = min(0.6 + match_count * 0.15, 1.0)
                categories.append({"slug": cat, "confidence": round(confidence, 2), "match_count": match_count})

    # Detect from image labels
    label_category = category_from_image_labels(image_labels)
    if label_category and not any(c["slug"] == label_category for c in categories):
        categories.append({"slug": label_category, "confidence": 0.7, "source": "image"})

    # Detect from explicit constraints
    if isinstance(constraints, dict):
        pt = constraints.get("product_type", "").lower().strip()
        if pt and not any(c["slug"] == pt for c in categories):
            categories.append({"slug": pt, "confidence": 1.0, "source": "constraint"})

    # Sort by confidence descending
    categories.sort(key=lambda c: c["confidence"], reverse=True)

    # Extract brands
    if text:
        for brand_name, pattern in _brand_patterns_for(pid):
            if pattern.search(text):
                brands.append(brand_name)

    # Extract use-cases
    if text:
        for use_case, pattern in _use_case_patterns_for(pid):
            if pattern.search(text):
                use_cases.append(use_case)

    # Extract specs
    if text:
        for spec_name, unit, pattern in _spec_patterns_for(pid):
            m = pattern.search(text)
            if m:
                specs[spec_name] = {"value": m.group(1), "unit": unit}

    primary = categories[0]["slug"] if categories else detect_category(query, image_labels, constraints)

    return {
        "categories": categories,
        "brands": brands,
        "use_cases": use_cases,
        "specs": specs,
        "primary_category": primary,
        "multi_category": len(categories) > 1,
    }
