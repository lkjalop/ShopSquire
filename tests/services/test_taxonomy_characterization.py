"""Phase 0c — taxonomy characterization baseline (the F2 split-brain parity record).

ShopSquire has TWO product taxonomies wired into one request path:
  - product_classifier.classify_product_type  (config/store_vocab.json)  ← core finalizer + cart upsell
  - product_taxonomy.infer_product_family     (hard-coded families)      ← recommend body + checkout_upsell

They DISAGREE materially (documented below). This test PINS their current outputs so the Phase 1
consolidation (One StoreTaxonomy) has a parity baseline: when the divergence is fixed, THIS test
changes, and that diff is the record of the fix. It is a characterization (golden) test — it
documents what IS, not what SHOULD be. Do not "fix" it by editing values; fix the taxonomy.
"""
from __future__ import annotations

import pytest

from src.app.services.product_classifier import (
    classify_product_type,
    companion_types_for,
    primary_types,
)
from src.app.services.product_taxonomy import infer_product_family


# (name, classify_product_type, infer_product_family).
# Phase 1 (One StoreTaxonomy, commit-this-change): infer_product_family now DERIVES from
# classify_product_type (one brain), so the family code agrees with the type. The four ✓FIXED
# rows below changed from the 0c baseline — that diff IS the F2 fix record.
_CORPUS = [
    ("ASUS ROG Strix G16 Gaming Laptop", "laptop", "LAP"),
    ("MacBook Pro 14", "laptop", "LAP"),
    ("Dell XPS 13", "laptop", "LAP"),               # ✓FIXED (was UNK) — derives from classify=laptop
    ("Lenovo ThinkPad X1", "laptop", "LAP"),        # ✓FIXED (was UNK) — derives from classify=laptop
    ("LG UltraGear 27 Monitor", "monitor", "MON"),
    ("Logitech MX Master 3 Mouse", "peripheral", "PERIPH"),
    ("Keychron K2 Mechanical Keyboard", "peripheral", "PERIPH"),
    ("SteelSeries Arctis 7 Headset", "audio", "HEAD"),
    ("Samsung T7 External SSD", "storage", "ACC"),
    ("Anker USB-C Hub", "peripheral", "ACC"),
    ("Razer Laptop Cooling Pad", "peripheral", "COOL"),  # ✓FIXED (was LAP) — accessory, not primary
    ("Targus Laptop Backpack", "bag", "BAG"),            # ✓FIXED (was LAP) — bag, not primary
    ("HP Pavilion Desktop Tower", "desktop", "UNK"),
    ("Generic Widget 9000", "accessory", "UNK"),
    ("iPhone 15 Pro", "accessory", "UNK"),
    ("iPad Air", "tablet", "UNK"),
]


@pytest.mark.parametrize("name,expected_type,_fam", _CORPUS)
def test_classify_product_type_baseline(name, expected_type, _fam):
    assert classify_product_type(name) == expected_type


@pytest.mark.parametrize("name,_type,expected_family", _CORPUS)
def test_infer_product_family_baseline(name, _type, expected_family):
    assert infer_product_family(name=name) == expected_family


def test_companion_and_primary_baseline():
    assert sorted(primary_types()) == ["desktop", "laptop"]
    assert companion_types_for("laptop") == ["bag", "audio", "storage", "monitor", "peripheral", "networking"]


def test_f2_divergences_are_resolved():
    """Phase 1: the two F2 divergences are now FIXED by the unified taxonomy (one brain)."""
    # 1. Brand/model laptops now recognised as LAP (family derives from classify=laptop):
    for n in ("Dell XPS 13", "Lenovo ThinkPad X1"):
        assert classify_product_type(n) == "laptop"
        assert infer_product_family(name=n) == "LAP"   # was UNK — resolved

    # 2. "Laptop"-named accessories are NO LONGER mis-filed as the primary product:
    assert infer_product_family(name="Razer Laptop Cooling Pad") == "COOL"   # was LAP
    assert infer_product_family(name="Targus Laptop Backpack") == "BAG"      # was LAP
    # Neither is treated as a primary laptop now.
    assert infer_product_family(name="Razer Laptop Cooling Pad") != "LAP"
    assert infer_product_family(name="Targus Laptop Backpack") != "LAP"


def test_sku_prefix_remains_authoritative():
    # The SKU family code wins over name substrings (a SYN-ACC- item named "Gaming Laptop"
    # is still an accessory) — the prefix path must survive the unification.
    from src.app.services.product_taxonomy import infer_product_family as f
    assert f(sku="ACC-9", name="Gaming Laptop") == "ACC"
    assert f(sku="LAP-001", name="anything") == "LAP"
