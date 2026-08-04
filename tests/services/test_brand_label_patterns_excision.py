"""Phase 2 — recommend.py _BRAND_LABEL_PATTERNS excised to StoreProfile.brand_label_patterns.

Pure excision (zero behaviour change): the profile slot is byte-identical to the inline fallback,
and the inline fallback is byte-identical to the dict that used to live in suggest(). Image→brand
hint detection therefore behaves exactly as before.
"""
from __future__ import annotations

from src.app.platform.store_profile import brand_label_patterns as _profile_blp
# Now lives in the extracted image-hints service (re-exported by recommend.py for back-compat).
from src.app.services.recommend_image_hints import _BRAND_LABEL_PATTERNS_FALLBACK, _brand_label_patterns


def test_derived_patterns_match_inline_fallback_setwise():
    # brand_label_patterns is now DERIVED from the 3-axis `manufacturers` map; image-hint uses
    # any(p in label) so order within a manufacturer is irrelevant — compare sets.
    derived = _profile_blp("electronics")
    assert set(derived) == set(_BRAND_LABEL_PATTERNS_FALLBACK)
    for mfr, pats in _BRAND_LABEL_PATTERNS_FALLBACK.items():
        assert set(derived[mfr]) == {p.lower() for p in pats}


def test_helper_reads_derived_patterns():
    derived = _brand_label_patterns()
    for mfr, pats in _BRAND_LABEL_PATTERNS_FALLBACK.items():
        assert set(derived[mfr]) == {p.lower() for p in pats}


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
