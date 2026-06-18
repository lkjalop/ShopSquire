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


# (name, classify_product_type, infer_product_family) — captured 2026-06-18.
_CORPUS = [
    ("ASUS ROG Strix G16 Gaming Laptop", "laptop", "LAP"),
    ("MacBook Pro 14", "laptop", "LAP"),
    ("Dell XPS 13", "laptop", "UNK"),               # ⚠ F2: family fails to recognize XPS
    ("Lenovo ThinkPad X1", "laptop", "UNK"),        # ⚠ F2: family fails to recognize ThinkPad
    ("LG UltraGear 27 Monitor", "monitor", "MON"),
    ("Logitech MX Master 3 Mouse", "peripheral", "PERIPH"),
    ("Keychron K2 Mechanical Keyboard", "peripheral", "PERIPH"),
    ("SteelSeries Arctis 7 Headset", "audio", "HEAD"),
    ("Samsung T7 External SSD", "storage", "ACC"),
    ("Anker USB-C Hub", "peripheral", "ACC"),
    ("Razer Laptop Cooling Pad", "peripheral", "LAP"),   # ⚠ F2: accessory mis-filed as PRIMARY
    ("Targus Laptop Backpack", "bag", "LAP"),            # ⚠ F2: bag mis-filed as PRIMARY
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


def test_documents_known_f2_divergences():
    """Explicit record of the disagreements Phase 1 (One StoreTaxonomy) must resolve."""
    # 1. Brand/model laptops the family classifier doesn't recognize (returns UNK):
    for n in ("Dell XPS 13", "Lenovo ThinkPad X1"):
        assert classify_product_type(n) == "laptop"
        assert infer_product_family(name=n) == "UNK"   # divergence

    # 2. Accessories the family classifier mis-files as the PRIMARY product (LAP) via the
    #    'laptop' substring — a real bug: a cooling pad / backpack must NOT look like a laptop.
    for n in ("Razer Laptop Cooling Pad", "Targus Laptop Backpack"):
        assert classify_product_type(n) in ("peripheral", "bag")   # correct
        assert infer_product_family(name=n) == "LAP"               # WRONG (documented)
