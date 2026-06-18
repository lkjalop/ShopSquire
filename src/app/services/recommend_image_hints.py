"""Image-hint stage — extracted from recommend.py::suggest() (core/adapter split).

CORE mechanism: turn a (possibly untrusted) uploaded image's labels/CV-signals into a SAFE,
bounded set of brand/category/use-case hints for retrieval, dropping anything unsafe (OCR/QR/PII
payloads never become ranking signal). Pure functions — no DB, no request locals.

ADAPTER (flavour): the brand→manufacturer patterns come from the StoreProfile (3-axis
`manufacturers` map, via store_profile.brand_label_patterns). The `_SAFE_IMAGE_*` constant sets
are still inline electronics flavour — the next excision profile-backs them (a non-electronics
vertical supplies its own safe brands/categories). Tracked, not hidden.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# ── Brand→manufacturer label patterns (ADAPTER: derived from the StoreProfile) ──
# Inline fallback is byte-identical to the profile (parity-tested) so behaviour is unchanged if
# the profile is unreadable. A non-electronics vertical supplies its own patterns (or none).
_BRAND_LABEL_PATTERNS_FALLBACK: Dict[str, List[str]] = {
    "apple":     ["macbook", "imac", "mac mini", "mac pro", "apple"],
    "lenovo":    ["thinkpad", "ideapad", "legion", "yoga", "lenovo"],
    "dell":      ["xps", "inspiron", "alienware", "latitude", "dell"],
    "hp":        ["spectre", "envy", "omen", "elitebook", "probook", "hp laptop", "hp"],
    "asus":      ["rog", "zenbook", "vivobook", "asus"],
    "acer":      ["predator", "aspire", "swift", "nitro", "acer"],
    "msi":       ["msi", "dragon logo", "stealth", "raider", "titan", "creator"],
    "razer":     ["razer", "blade"],
    "microsoft": ["surface", "surface pro", "surface laptop"],
    "samsung":   ["galaxy book", "samsung"],
    "gigabyte":  ["aorus", "gigabyte"],
    "toshiba":   ["dynabook", "toshiba"],
}


def _brand_label_patterns() -> Dict[str, List[str]]:
    """Image→manufacturer label patterns, DERIVED from the profile's 3-axis `manufacturers`
    map (store_profile.brand_label_patterns). Falls back to the inline copy if unavailable."""
    try:
        from src.app.platform.store_profile import brand_label_patterns as _blp
        val = _blp()
        if isinstance(val, dict) and val:
            return val
    except Exception:
        pass
    return _BRAND_LABEL_PATTERNS_FALLBACK


# Manufacturers the fast-path image hinting supports (ADAPTER flavour — profile-back next).
_SUPPORTED_IMAGE_BRAND_HINTS = {
    "apple", "asus", "lenovo", "hp", "dell", "msi",
    "alienware", "microsoft", "acer", "samsung", "razer", "gigabyte", "toshiba",
}

_SAFE_IMAGE_BRANDS_FALLBACK = frozenset({
    "acer", "alienware", "apple", "asus", "dell", "hp", "lenovo",
    "macbook", "microsoft", "msi", "samsung", "surface",
})

_SAFE_IMAGE_CATEGORIES_FALLBACK = frozenset({
    "chromebook", "computer", "desktop", "gaming", "laptop", "macbook",
    "notebook", "pc", "tablet", "windows",
})


def _safe_image_brands() -> frozenset:
    """Curated safe brand allow-list from the StoreProfile (safe_image_brands slot)."""
    try:
        from src.app.platform.store_profile import profile_slot
        val = profile_slot("safe_image_brands", default=None)
        if isinstance(val, (list, set, tuple)) and val:
            return frozenset(str(x).lower() for x in val)
    except Exception:
        pass
    return _SAFE_IMAGE_BRANDS_FALLBACK


def _safe_image_categories() -> frozenset:
    """Curated safe category allow-list from the StoreProfile (safe_image_categories slot)."""
    try:
        from src.app.platform.store_profile import profile_slot
        val = profile_slot("safe_image_categories", default=None)
        if isinstance(val, (list, set, tuple)) and val:
            return frozenset(str(x).lower() for x in val)
    except Exception:
        pass
    return _SAFE_IMAGE_CATEGORIES_FALLBACK


# Back-compat module attributes (some call-sites/tests reference these names directly).
_SAFE_IMAGE_BRANDS = _SAFE_IMAGE_BRANDS_FALLBACK
_SAFE_IMAGE_CATEGORIES = _SAFE_IMAGE_CATEGORIES_FALLBACK

# CV-signal fields that are UNTRUSTED content (OCR/QR/links) — never a ranking signal.
_UNSAFE_IMAGE_SIGNAL_KEYS = {
    "external_url", "extracted_text", "linked_artifact", "ocr_text",
    "qr_payloads", "qr_redirect_probe", "raw_ocr",
}


def _safe_image_hints_for_fast_path(
    *,
    image_context: Dict[str, Any],
    image_cv_signals: Dict[str, Any],
    query: str,
) -> Dict[str, Any]:
    labels = [str(x or "").lower() for x in (image_context.get("labels") or []) if str(x or "").strip()]
    product_identity = image_context.get("product_identity") if isinstance(image_context.get("product_identity"), dict) else {}
    text_blob = " ".join(labels + [str(query or "").lower()])

    safe_brands = _safe_image_brands()
    safe_categories = _safe_image_categories()

    brand_hints: list[str] = []
    for brand in safe_brands:
        if re.search(rf"(?<![a-z0-9]){re.escape(brand)}(?![a-z0-9])", text_blob):
            brand_hints.append("apple" if brand == "macbook" else brand)
    pi_brand = str(product_identity.get("brand") or "").strip().lower()
    if pi_brand in safe_brands:
        brand_hints.append("apple" if pi_brand == "macbook" else pi_brand)

    category_hints: list[str] = []
    for category in safe_categories:
        if re.search(rf"(?<![a-z0-9]){re.escape(category)}(?![a-z0-9])", text_blob):
            category_hints.append("laptop" if category in {"gaming", "notebook", "pc", "windows"} else category)
    pi_category = str(product_identity.get("category") or product_identity.get("product_type") or "").strip().lower()
    if pi_category in safe_categories:
        category_hints.append("laptop" if pi_category in {"gaming", "notebook", "pc", "windows"} else pi_category)

    use_case_hints: list[str] = []
    if re.search(r"(?i)\b(gaming|rtx|gpu|fps|144hz|4070|4060|4050|3050)\b", text_blob):
        use_case_hints.append("gaming")
        category_hints.append("laptop")

    unsafe_flags = {
        "fast_triage_timeout": bool(image_cv_signals.get("fast_triage_timeout")),
        "manipulation_detected": bool(image_cv_signals.get("manipulation_detected")),
        "ocr_prompt_injection": bool(image_cv_signals.get("ocr_prompt_injection")),
        "pii_detected": bool(image_cv_signals.get("pii_detected")),
        "qr_code_detected": bool(image_cv_signals.get("qr_code_detected")),
        "qr_external_url_detected": bool(image_cv_signals.get("qr_external_url_detected")),
        "qr_prompt_injection": bool(image_cv_signals.get("qr_prompt_injection")),
        "ssn_detected": bool(image_cv_signals.get("ssn_detected")),
        "steg_suspicious": bool(image_cv_signals.get("steg_suspicious")),
    }
    return {
        "brand_hints": list(dict.fromkeys(brand_hints))[:3],
        "category_hints": list(dict.fromkeys(category_hints))[:4],
        "use_case_hints": list(dict.fromkeys(use_case_hints))[:2],
        "trust_state": "under_review" if any(unsafe_flags.values()) else "trusted",
        "unsafe_flags": unsafe_flags,
        "dropped_fields": sorted(_UNSAFE_IMAGE_SIGNAL_KEYS),
    }
