"""Accessory FAMILY taxonomy — VERTICAL-BLIND CORE.

Projects a product onto an accessory-family code (LAP/MON/BAG/COOL/ACC/PERIPH/HEAD for
electronics), an accessory slug, and a tag set. This module carries NO flavour: the family
codes, SKU-prefix map, keyword/slug maps, type->family map and fallback order are resolved
PER REQUEST from the active StoreProfile (cached by profile id). An electronics tenant gets
electronics families (config/store_profiles/electronics.json taxonomy slots, excised verbatim
from the old hardcoded dicts); a vertical that defines no taxonomy slots gets UNK families —
so an electronics-accessory family NEVER bleeds onto a non-electronics product.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Iterable


# ── Per-request (active-vertical) taxonomy resolution ────────────────────────────
@lru_cache(maxsize=8)
def _accessory_families_for(pid: str) -> frozenset:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("accessory_families", profile_id=pid, default=None)
    return frozenset(str(x) for x in raw) if isinstance(raw, list) else frozenset()


@lru_cache(maxsize=8)
def _sku_prefix_family_for(pid: str) -> Dict[str, str]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("sku_prefix_family", profile_id=pid, default=None)
    return dict(raw) if isinstance(raw, dict) else {}


@lru_cache(maxsize=8)
def _family_keywords_for(pid: str) -> Dict[str, tuple]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("family_keywords", profile_id=pid, default=None)
    return {k: tuple(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


@lru_cache(maxsize=8)
def _accessory_slug_keywords_for(pid: str) -> Dict[str, tuple]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("accessory_slug_keywords", profile_id=pid, default=None)
    return {k: tuple(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


@lru_cache(maxsize=8)
def _type_to_family_for(pid: str) -> Dict[str, str]:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("type_to_family", profile_id=pid, default=None)
    return dict(raw) if isinstance(raw, dict) else {}


@lru_cache(maxsize=8)
def _fallback_family_order_for(pid: str) -> tuple:
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("fallback_family_order", profile_id=pid, default=None)
    return tuple(str(x) for x in raw) if isinstance(raw, list) else ()


def _active_pid() -> str:
    from src.app.platform.store_profile import active_profile_id
    return active_profile_id()


def reset_cache() -> None:
    """Clear the per-profile taxonomy caches (test isolation / profile reload)."""
    for fn in (
        _accessory_families_for,
        _sku_prefix_family_for,
        _family_keywords_for,
        _accessory_slug_keywords_for,
        _type_to_family_for,
        _fallback_family_order_for,
    ):
        try:
            fn.cache_clear()
        except Exception:
            pass


# Back-compat module constant for direct importers (checkout_upsell). Derived once from the
# electronics profile — the default deployment vertical. Runtime membership checks use the
# per-request accessor via is_accessory_family().
ACCESSORY_FAMILIES = _accessory_families_for("electronics")


def _text_parts(*parts: Any) -> str:
    buf: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            for v in part.values():
                if isinstance(v, (str, int, float)):
                    buf.append(str(v))
                elif isinstance(v, list):
                    buf.extend(str(x) for x in v if x is not None)
        elif isinstance(part, list):
            buf.extend(str(x) for x in part if x is not None)
        elif part is not None:
            buf.append(str(part))
    return " ".join(buf).strip().lower()


# Phase 1 (One StoreTaxonomy): the PRIMARY product type comes from ONE brain —
# product_classifier.classify_product_type — and the SKU-family code is a deterministic
# projection of it. type_to_family covers the types classify expresses directly; the finer
# accessory sub-families classify can't express are recovered by the keyword fallback below.
# This kills the old divergence where infer_product_family did its own greedy substring
# matching (a primary-product model name -> UNK; "<primary> Cooling Pad" -> primary family).
def infer_product_family(*, sku: str | None = None, name: str | None = None, specs: Dict[str, Any] | None = None) -> str:
    pid = _active_pid()
    raw_sku = str(sku or "").strip().upper()
    for prefix, family in _sku_prefix_family_for(pid).items():
        if raw_sku.startswith(f"{prefix}-") or raw_sku == prefix:
            return family

    specs_dict = specs if isinstance(specs, dict) else {}

    # One brain: derive the primary family from the unified product-type classifier.
    try:
        from src.app.services.product_classifier import classify_product_type
        ptype = classify_product_type(name, specs_dict)
    except Exception:
        ptype = None
    fam = _type_to_family_for(pid).get(ptype or "")
    if fam:
        return fam

    # Coarse bucket (peripheral/accessory/desktop/tablet/unknown): recover the finer accessory
    # sub-family from keywords (the primary-product families are deliberately excluded from the
    # fallback order, since classify already ruled them out).
    haystack = _text_parts(raw_sku, name, specs_dict.get("category"), specs_dict.get("tags"), specs_dict)
    family_keywords = _family_keywords_for(pid)
    for family in _fallback_family_order_for(pid):
        if any(token in haystack for token in family_keywords.get(family, ())):
            return family
    return "UNK"


def infer_accessory_slug(*, sku: str | None = None, name: str | None = None, specs: Dict[str, Any] | None = None) -> str | None:
    specs_dict = specs if isinstance(specs, dict) else {}
    haystack = _text_parts(sku, name, specs_dict.get("category"), specs_dict.get("tags"), specs_dict)
    for slug, keywords in _accessory_slug_keywords_for(_active_pid()).items():
        if any(token in haystack for token in keywords):
            return slug
    return None


def product_tags(*, sku: str | None = None, name: str | None = None, specs: Dict[str, Any] | None = None) -> set[str]:
    specs_dict = specs if isinstance(specs, dict) else {}
    tags = {
        str(x).strip().lower().replace(" ", "_")
        for x in (specs_dict.get("tags") or [])
        if str(x).strip()
    }
    category = str(specs_dict.get("category") or "").strip().lower().replace(" ", "_")
    if category:
        tags.add(category)
    slug = infer_accessory_slug(sku=sku, name=name, specs=specs_dict)
    if slug:
        tags.add(slug)
    family = infer_product_family(sku=sku, name=name, specs=specs_dict)
    if family and family != "UNK":
        tags.add(f"family_{family.lower()}")
    return tags


def is_accessory_family(family: str | None) -> bool:
    return str(family or "").strip().upper() in _accessory_families_for(_active_pid())


def count_items(items: Iterable[Dict[str, Any]]) -> int:
    total = 0
    for item in items or []:
        try:
            total += max(1, int(item.get("quantity") or 1))
        except Exception:
            total += 1
    return total
