"""3-axis brand schema — manufacturer / product line / (type lives elsewhere).

The flat brand_label_patterns dict is now DERIVED from the structured `manufacturers` map.
Parity: the derived image→manufacturer patterns SET-equal the live 12-brand dict that used to
be inline in recommend.py. New capability: product_line_index resolves a sub-brand/range
(thinkpad → lenovo/ThinkPad) independently of product TYPE. Agnostic: pharmacy fills the same
three axes with zero laptop flavour.
"""
from __future__ import annotations

from src.app.platform.store_profile import (
    brand_label_patterns,
    get_store_profile,
    product_line_index,
)
from src.app.services.recommend_image_hints import _BRAND_LABEL_PATTERNS_FALLBACK


# ── Parity: derived patterns == the live inline dict (set-wise per manufacturer) ──
def test_derived_patterns_match_inline_fallback_setwise():
    derived = brand_label_patterns("electronics")
    assert set(derived) == set(_BRAND_LABEL_PATTERNS_FALLBACK)
    for mfr, pats in _BRAND_LABEL_PATTERNS_FALLBACK.items():
        # image-hint uses any(p in label) → order within a manufacturer is irrelevant; compare sets.
        assert set(derived[mfr]) == {p.lower() for p in pats}, f"drift for {mfr}"


# ── New axis: line resolution separates manufacturer / line / from type ──
def test_product_line_index_separates_line_from_manufacturer():
    idx = product_line_index("electronics")
    # A product LINE resolves to manufacturer + the line itself:
    assert idx["thinkpad"] == {"manufacturer": "lenovo", "line": "thinkpad"}
    assert idx["xps"] == {"manufacturer": "dell", "line": "xps"}
    assert idx["rog"] == {"manufacturer": "asus", "line": "rog"}
    # A manufacturer ALIAS resolves to the company with no specific line:
    assert idx["lenovo"] == {"manufacturer": "lenovo", "line": None}
    assert idx["asus"] == {"manufacturer": "asus", "line": None}


def test_line_index_is_independent_of_product_type():
    # 'thinkpad' is a LINE (brand axis); whether it's a laptop/desktop is the TYPE axis,
    # which the line index does not assert. The two axes are demarcated.
    idx = product_line_index("electronics")
    assert "manufacturer" in idx["thinkpad"] and "line" in idx["thinkpad"]
    assert "type" not in idx["thinkpad"] and "product_type" not in idx["thinkpad"]


# ── Agnostic proof: pharmacy fills the same schema with no laptop flavour ──
def test_pharmacy_manufacturers_agnostic():
    derived = brand_label_patterns("pharmacy")
    assert "blackmores" in derived
    assert "lenovo" not in derived and "asus" not in derived
    idx = product_line_index("pharmacy")
    assert idx["ultiboost"] == {"manufacturer": "swisse", "line": "ultiboost"}
    assert idx["panadol"] == {"manufacturer": "panadol", "line": None}
    # no electronics flavour leaked into the pharmacy brand axis:
    blob = " ".join(derived).lower() + " " + " ".join(idx.keys()).lower()
    for flavour in ("thinkpad", "macbook", "rog", "rtx"):
        assert flavour not in blob
