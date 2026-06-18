from __future__ import annotations

from typing import Any, Dict, Iterable


ACCESSORY_FAMILIES = {"ACC", "PERIPH", "HEAD", "MON", "COOL", "BAG"}

_SKU_PREFIX_FAMILY = {
    "LAP": "LAP",
    "ACC": "ACC",
    "PERIPH": "PERIPH",
    "HEAD": "HEAD",
    "MON": "MON",
    "COOL": "COOL",
    "BAG": "BAG",
}

_FAMILY_KEYWORDS = {
    "LAP": (
        "laptop",
        "notebook",
        "macbook",
        "ultrabook",
        "chromebook",
        "copilot+ pc",
        "copilot pc",
    ),
    "PERIPH": (
        "mouse",
        "keyboard",
        "keypad",
        "trackpad",
        "keyboard_mouse_combo",
        "gaming_mouse",
    ),
    "HEAD": (
        "headset",
        "headphone",
        "headphones",
        "earbuds",
        "earphones",
        "microphone",
        "speaker",
    ),
    "MON": (
        "monitor",
        "display",
        "portable monitor",
    ),
    "BAG": (
        "sleeve",
        "backpack",
        "bag",
        "case",
        "messenger",
        "carry",
    ),
    "COOL": (
        "cooling pad",
        "cooler",
        "laptop stand",
        "stand",
        "ergonomic riser",
    ),
    "ACC": (
        "dock",
        "docking",
        "hub",
        "adapter",
        "charger",
        "charging cable",
        "power bank",
        "stylus",
        "external ssd",
        "ssd",
        "card reader",
        "audio interface",
        "warranty",
        "screen protector",
        "cleaning kit",
        "color calibrator",
    ),
}

_ACCESSORY_SLUG_KEYWORDS = {
    "screen_protector": ("screen protector",),
    "cleaning_kit": ("cleaning kit",),
    "laptop_sleeve": ("laptop sleeve", "sleeve"),
    "usb_hub": ("usb hub", "usb-c hub", "hub"),
    "dock": ("dock", "docking station"),
    "monitor": ("monitor", "portable monitor"),
    "keyboard_mouse_combo": ("keyboard_mouse_combo", "keyboard + mouse", "keyboard mouse combo"),
    "compact_charger": ("compact charger", "charger"),
    "power_bank": ("power bank",),
    "headset": ("headset",),
    "mouse": ("mouse",),
    "external_ssd": ("external ssd",),
    "stylus": ("stylus", "pen"),
    "color_calibrator": ("color calibrator",),
    "extra_charging_cable": ("charging cable", "usb-c cable"),
    "laptop_stand": ("laptop stand", "stand"),
    "cooling_pad": ("cooling pad",),
    "gaming_mouse": ("gaming mouse",),
    "extended_warranty": ("extended warranty", "warranty"),
    "card_reader": ("card reader",),
    "audio_interface": ("audio interface",),
    "headphones": ("headphones", "headphone"),
}


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
# projection of it. This map covers the types classify expresses directly; the finer
# accessory sub-families (COOL/ACC/PERIPH/HEAD/BAG) classify can't express are recovered by
# the keyword fallback below. This kills the old divergence where infer_product_family did
# its own greedy substring matching (XPS/ThinkPad -> UNK; "Laptop Cooling Pad" -> LAP).
_TYPE_TO_FAMILY = {
    "laptop": "LAP",
    "monitor": "MON",
    "bag": "BAG",
    "audio": "HEAD",
    "storage": "ACC",
}

# Fallback families for classify's coarse buckets (peripheral/accessory/desktop/tablet/unknown).
# LAP and MON are deliberately EXCLUDED: classify owns "is this a primary laptop/monitor", so a
# stray "laptop"/"monitor" substring in an accessory name must not promote it to the primary type.
_FALLBACK_FAMILY_ORDER = ("COOL", "BAG", "ACC", "PERIPH", "HEAD")


def infer_product_family(*, sku: str | None = None, name: str | None = None, specs: Dict[str, Any] | None = None) -> str:
    raw_sku = str(sku or "").strip().upper()
    for prefix, family in _SKU_PREFIX_FAMILY.items():
        if raw_sku.startswith(f"{prefix}-") or raw_sku == prefix:
            return family

    specs_dict = specs if isinstance(specs, dict) else {}

    # One brain: derive the primary family from the unified product-type classifier.
    try:
        from src.app.services.product_classifier import classify_product_type
        ptype = classify_product_type(name, specs_dict)
    except Exception:
        ptype = None
    fam = _TYPE_TO_FAMILY.get(ptype or "")
    if fam:
        return fam

    # Coarse bucket (peripheral/accessory/desktop/tablet/unknown): recover the finer accessory
    # sub-family from keywords (NOT LAP/MON — classify already ruled those out).
    haystack = _text_parts(raw_sku, name, specs_dict.get("category"), specs_dict.get("tags"), specs_dict)
    for family in _FALLBACK_FAMILY_ORDER:
        if any(token in haystack for token in _FAMILY_KEYWORDS[family]):
            return family
    return "UNK"


def infer_accessory_slug(*, sku: str | None = None, name: str | None = None, specs: Dict[str, Any] | None = None) -> str | None:
    specs_dict = specs if isinstance(specs, dict) else {}
    haystack = _text_parts(sku, name, specs_dict.get("category"), specs_dict.get("tags"), specs_dict)
    for slug, keywords in _ACCESSORY_SLUG_KEYWORDS.items():
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
    return str(family or "").strip().upper() in ACCESSORY_FAMILIES


def count_items(items: Iterable[Dict[str, Any]]) -> int:
    total = 0
    for item in items or []:
        try:
            total += max(1, int(item.get("quantity") or 1))
        except Exception:
            total += 1
    return total
