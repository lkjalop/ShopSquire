"""Product-type classification + price-anomaly guard — agnostic core (2026-06).

ROOT CAUSE this addresses: the `products` schema has no `product_type`/`category`
column (only name, price_cents, specs). The demo catalog is a *mixed* electronics
feed (laptops, monitors, routers, headsets, bags, SSDs, tablets) yet the seeder
stamps every SKU `LAP-`. So nothing in the data distinguishes a laptop from a
Wi-Fi extender — which is why a $59 range-extender leaked into "laptop for uni"
results. Gating on PRICE was the wrong axis (a $59 product can be perfectly valid);
gating on TYPE is correct.

This module is the MECHANISM; the FLAVOUR (which name patterns map to which type,
and the sane price band per type) lives in the StoreProfile
(``config/store_profiles/<id>.json``) so the same core serves any vertical. One
classifier drives three surfaces:

  1. Recommendation gating  — keep PRIMARY types in headline results (services/.. → recommend.py)
  2. Cart upsell            — route accessories to companion cross-sell (upsell_engine.py)
  3. Price-anomaly security — flag prices outside a type's band as possible data
     poisoning / business-loss vectors (a poisoned $45 price on a real laptop is a
     direct margin loss the moment a buyer checks out).

Pure functions, no I/O beyond a cached config read. Never raises.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

# Baked-in catastrophic fallback so the core still classifies if the profile is unreadable.
_FALLBACK: Dict[str, Any] = {
    "primary_types": ["laptop", "desktop"],
    "product_type_rules": [
        {"type": "networking", "pattern": r"\b(router|modem|range extender|wi-?fi extender|mesh|access point|powerline)\b"},
        {"type": "monitor", "pattern": r"\b(monitor|display)\b"},
        {"type": "audio", "pattern": r"\b(head ?set|cloud flight|earbuds?|ear ?phones?|speakers?|microphone|soundbar)\b"},
        {"type": "storage", "pattern": r"\b(ssd|hdd|hard drive|flash drive|usb drive|sd card|micro ?sd|memory card|portable ssd)\b"},
        {"type": "bag", "pattern": r"\b(backpack|brief|attache|folio|sleeve|carry ?bag|carry case|laptop case)\b"},
        {"type": "peripheral", "pattern": r"\b(mouse|keyboard|webcam|docking station|usb hub|laptop stand|cooling pad|charger|adapter|hdmi|cable|card reader)\b"},
        {"type": "printer", "pattern": r"\b(printer|scanner|ink|toner)\b"},
        {"type": "tablet", "pattern": r"\b(ipad|tablet|galaxy tab|surface go|surface pro)\b"},
        {"type": "desktop", "pattern": r"\b(desktop|tower pc|gaming pc|all-in-one|mini pc)\b"},
        {"type": "laptop", "pattern": r"\b(laptop|notebook|macbook|ultrabook|2-in-1|chromebook)\b"},
    ],
    "price_bands": {
        "laptop": [350, 6000], "desktop": [400, 9000], "tablet": [150, 3000],
        "monitor": [80, 3000], "networking": [25, 900], "audio": [10, 600],
        "storage": [10, 800], "bag": [15, 400], "peripheral": [5, 500],
        "printer": [40, 1500], "accessory": [5, 1500],
    },
    "upsell_companions": {
        "laptop": ["bag", "audio", "storage", "monitor", "peripheral", "networking"],
        "desktop": ["monitor", "peripheral", "audio", "storage", "networking"],
        "tablet": ["bag", "audio", "storage", "peripheral"],
    },
}

ACCESSORY_TYPE = "accessory"


@lru_cache(maxsize=1)
def _vocab() -> Dict[str, Any]:
    """Taxonomy vocab from the StoreProfile (SSOT — config/store_profiles/<id>.json).

    Phase 1: this used to read config/store_vocab.json (a parallel, drifting second profile).
    It now reads the canonical StoreProfile. `_FALLBACK` is dormant CATASTROPHIC insurance —
    it only fires if the profile is entirely unreadable (the loader itself already falls back
    to electronics for a missing/typo'd profile id)."""
    merged = dict(_FALLBACK)
    try:
        from src.app.platform.store_profile import get_store_profile
        prof = get_store_profile()  # default electronics; loader handles missing/typo'd ids
        if prof.get("primary_types"):
            merged["primary_types"] = prof["primary_types"]
        if prof.get("product_type_rules"):
            merged["product_type_rules"] = prof["product_type_rules"]
        if prof.get("price_bands_usd"):
            merged["price_bands"] = prof["price_bands_usd"]
        if prof.get("upsell_companions"):
            merged["upsell_companions"] = prof["upsell_companions"]
    except Exception:
        pass
    return merged


def reset_cache() -> None:
    """Clear the taxonomy caches — call when the active profile changes (tests/determinism)."""
    for fn in (_vocab, _compiled_rules):
        try:
            fn.cache_clear()
        except Exception:
            pass


@lru_cache(maxsize=1)
def _compiled_rules() -> List[Tuple[str, "re.Pattern[str]"]]:
    out: List[Tuple[str, "re.Pattern[str]"]] = []
    for rule in _vocab().get("product_type_rules", []):
        try:
            out.append((str(rule["type"]), re.compile(rule["pattern"], re.IGNORECASE)))
        except Exception:
            continue
    return out


def classify_product_type(name: Optional[str], specs: Optional[Dict[str, Any]] = None) -> str:
    """Map a product name → canonical type. First matching rule wins; accessory
    rules are ordered before 'laptop' so 'Laptop Brief' → 'bag'. An explicit
    specs['product_type'] (e.g. set at seed time) is trusted first. Defaults to
    'accessory' when nothing matches (fail safe: unknown ≠ primary)."""
    try:
        if isinstance(specs, dict):
            pt = str(specs.get("product_type") or "").strip().lower()
            if pt:
                return pt
        text = str(name or "")
        if not text.strip():
            return ACCESSORY_TYPE
        for ptype, rx in _compiled_rules():
            if rx.search(text):
                return ptype
        return ACCESSORY_TYPE
    except Exception:
        return ACCESSORY_TYPE


def primary_types() -> set:
    return {str(t).lower() for t in _vocab().get("primary_types", [])}


def is_primary_type(ptype: Optional[str]) -> bool:
    return str(ptype or "").lower() in primary_types()


def is_primary_product(name: Optional[str], specs: Optional[Dict[str, Any]] = None) -> bool:
    """Convenience: is this product one of the store's headline types (laptop/desktop)?"""
    return is_primary_type(classify_product_type(name, specs))


def companion_types_for(ptype: Optional[str]) -> List[str]:
    """Cart-upsell companion types for a primary item (laptop → bag/audio/storage…)."""
    return list(_vocab().get("upsell_companions", {}).get(str(ptype or "").lower(), []))


# ── Price-anomaly / poisoning guard ──────────────────────────────────────────

def price_band_for_type(ptype: Optional[str]) -> Optional[Tuple[float, float]]:
    band = _vocab().get("price_bands", {}).get(str(ptype or "").lower())
    if isinstance(band, (list, tuple)) and len(band) == 2:
        try:
            return float(band[0]), float(band[1])
        except Exception:
            return None
    return None


def price_anomaly(price: Optional[float], ptype: Optional[str]) -> Optional[str]:
    """Return 'underpriced' / 'overpriced' / None for a price vs its type band.

    SECURITY framing (shift-left, agnostic core): a price outside its type band is
    a data-integrity signal, not a pricing opinion. The high-severity case is
    'underpriced' — if a catalog/feed is poisoned (compromised supplier feed,
    tampered import, injected DB row) so a $1,800 laptop reads $45, every checkout
    bleeds margin instantly and at scale. 'overpriced' is denial-of-inventory /
    reputational. Either way the recommender should NOT silently surface or sell it.
    """
    try:
        if price is None:
            return None
        band = price_band_for_type(ptype)
        if not band:
            return None
        lo, hi = band
        p = float(price)
        if p <= 0:
            return "underpriced"
        if p < lo:
            return "underpriced"
        if p > hi:
            return "overpriced"
        return None
    except Exception:
        return None


def annotate_product(item: Dict[str, Any]) -> Dict[str, Any]:
    """Annotate a result dict in place with product_type + price_anomaly. Used by the
    recommend choke point so trace/source_statuses and upsell can consume it."""
    try:
        if not isinstance(item, dict):
            return item
        name = item.get("name")
        specs = item.get("specs") if isinstance(item.get("specs"), dict) else None
        ptype = classify_product_type(name, specs)
        item["product_type"] = ptype
        price = item.get("price")
        if price is None and item.get("price_cents") is not None:
            try:
                price = int(item["price_cents"]) / 100.0
            except Exception:
                price = None
        anomaly = price_anomaly(price, ptype)
        if anomaly:
            item["price_anomaly"] = anomaly
    except Exception:
        pass
    return item
