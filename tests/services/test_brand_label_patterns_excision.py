"""Phase 2 — recommend.py _BRAND_LABEL_PATTERNS excised to StoreProfile.brand_label_patterns.

Pure excision (zero behaviour change): the profile slot is byte-identical to the inline fallback,
and the inline fallback is byte-identical to the dict that used to live in suggest(). Image→brand
hint detection therefore behaves exactly as before.
"""
from __future__ import annotations

from src.app.platform.store_profile import get_store_profile
from src.app.routers.recommend import _BRAND_LABEL_PATTERNS_FALLBACK, _brand_label_patterns


def test_profile_slot_matches_inline_fallback_verbatim():
    prof = get_store_profile("electronics").get("brand_label_patterns")
    assert prof == _BRAND_LABEL_PATTERNS_FALLBACK


def test_helper_reads_profile():
    assert _brand_label_patterns() == _BRAND_LABEL_PATTERNS_FALLBACK


def test_image_brand_hint_mappings_unchanged():
    pats = _brand_label_patterns()

    def _infer(label: str):
        low = label.lower()
        for brand, patterns in pats.items():
            if any(p in low for p in patterns):
                return brand
        return None

    assert _infer("MacBook Pro") == "apple"
    assert _infer("ThinkPad X1") == "lenovo"
    assert _infer("Dell XPS 15") == "dell"
    assert _infer("ASUS ROG Strix") == "asus"
    assert _infer("MSI Stealth") == "msi"
    assert _infer("Razer Blade") == "razer"
    assert _infer("Surface Laptop") == "microsoft"
    assert _infer("a plain headset") is None


def test_fallback_is_twelve_brands():
    # The full electronics brand set (the live dict before excision).
    assert set(_BRAND_LABEL_PATTERNS_FALLBACK) == {
        "apple", "lenovo", "dell", "hp", "asus", "acer", "msi",
        "razer", "microsoft", "samsung", "gigabyte", "toshiba",
    }
