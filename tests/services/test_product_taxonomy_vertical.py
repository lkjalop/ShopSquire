"""product_taxonomy accessory-family inference is PER-REQUEST profile-scoped — no bleed.

The accessory FAMILY taxonomy (LAP/MON/BAG/COOL/ACC/PERIPH/HEAD) is electronics flavour that
now lives in electronics.json. product_taxonomy is vertical-blind: an electronics tenant gets
electronics families; a vertical with no taxonomy slots gets UNK families — so an electronics
accessory family NEVER bleeds onto a non-electronics product (e.g. a leather messenger bag must
NOT be tagged with the electronics BAG accessory family).
"""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id
from src.app.services import product_taxonomy as pt


@contextlib.contextmanager
def _vertical(pid: str):
    token = set_active_profile_id(pid)
    pt.reset_cache()
    try:
        yield
    finally:
        reset_active_profile_id(token)
        pt.reset_cache()


def test_electronics_infers_families():
    with _vertical("electronics"):
        assert pt.infer_product_family(sku="LAP-001", name="Acme Pro 15") == "LAP"
        assert pt.infer_product_family(name="Laptop Cooling Pad") == "COOL"
        assert pt.infer_product_family(name="Leather Messenger Bag", specs={"tags": ["bag"]}) == "BAG"
        assert pt.is_accessory_family("BAG") is True
        assert pt.is_accessory_family("LAP") is False  # LAP is a primary family, not accessory


def test_fashion_no_electronics_family_bleed():
    with _vertical("fashion"):
        # a fashion bag must NOT pick up the electronics BAG accessory family
        assert pt.infer_product_family(name="Leather Messenger Bag", specs={"tags": ["bag"]}) == "UNK"
        # an electronics SKU prefix means nothing under fashion
        assert pt.infer_product_family(sku="COOL-9", name="Cooling Pad") == "UNK"
        assert pt.infer_accessory_slug(name="USB-C Docking Station") is None


def test_pharmacy_no_electronics_family_bleed():
    with _vertical("pharmacy"):
        assert pt.infer_product_family(name="Laptop Cooling Pad") == "UNK"
        assert pt.is_accessory_family("ACC") is False  # pharmacy defines no accessory families


def test_accessory_families_backcompat_constant_is_electronics():
    # checkout_upsell imports the module constant directly — it must stay the electronics set.
    assert pt.ACCESSORY_FAMILIES == frozenset({"ACC", "PERIPH", "HEAD", "MON", "COOL", "BAG"})
