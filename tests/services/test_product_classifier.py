"""Product-type classifier + price-anomaly (poisoning) guard — agnostic core."""
from __future__ import annotations

from src.app.services.product_classifier import (
    classify_product_type,
    is_primary_product,
    companion_types_for,
    price_anomaly,
    annotate_product,
)


def test_real_laptops_classify_as_laptop():
    for n in [
        'Asus VivoBook 15.6" Full HD Thin & Light Laptop (1TB)',
        "Dell 15 DC15250 15.6\" Full HD Laptop (Intel Core i5)",
        "Lenovo Ideapad 5 14\" WUXGA OLED 2-in-1 Laptop",
        "HP Victus 15-fa2364TX Gaming Laptop",
    ]:
        assert classify_product_type(n) == "laptop", n
        assert is_primary_product(n)


def test_accessories_are_not_primary():
    cases = {
        "TP-Link AC750 Wi-Fi Range Extender": "networking",
        "ASUS RT-AX54HP V2 AX1800 Wi-Fi 6 Router": "networking",
        "STM Tower View Folio 18\" Laptop Brief (Black)": "bag",   # 'Laptop' present but it's a bag
        "Thule Gauntlet Macbook Pro Attache 14\"": "bag",
        "HyperX Cloud Flight 2 Wireless Gaming Headset": "audio",
        "Sandisk E30 Portable SSD Drive (1TB)": "storage",
        "27\" FHD 240Hz Curved Gaming Monitor": "monitor",
        "Pixma Home Printer": "printer",
        'iPad 11" Wi-Fi 128GB (Grey)': "tablet",
    }
    for name, expected in cases.items():
        assert classify_product_type(name) == expected, (name, classify_product_type(name))
        assert not is_primary_product(name), name


def test_laptop_brief_is_a_bag_not_a_laptop():
    # The exact leak that motivated this: a 'Laptop Brief' must not count as a laptop.
    assert classify_product_type("STM Tower View Folio 18\" Laptop Brief") == "bag"


def test_unknown_defaults_to_accessory_not_primary():
    assert classify_product_type("Mystery Gadget 3000") == "accessory"
    assert not is_primary_product("Mystery Gadget 3000")


def test_specs_product_type_is_trusted_first():
    assert classify_product_type("anything", {"product_type": "desktop"}) == "desktop"


def test_companion_types_for_laptop_upsell():
    comps = companion_types_for("laptop")
    assert "bag" in comps and "audio" in comps and "storage" in comps


def test_price_anomaly_flags_poisoned_underprice():
    # A real laptop poisoned to $45 → underpriced (direct margin-loss vector).
    assert price_anomaly(45, "laptop") == "underpriced"
    assert price_anomaly(0, "laptop") == "underpriced"
    assert price_anomaly(50000, "laptop") == "overpriced"
    assert price_anomaly(1499, "laptop") is None  # normal laptop price = clean


def test_price_anomaly_respects_type_band():
    # $59 is normal for a range-extender (networking) — NOT an anomaly, just wrong type.
    assert price_anomaly(59, "networking") is None
    assert price_anomaly(45, "bag") is None  # cheap bag is fine


def test_annotate_product_sets_type_and_anomaly():
    item = {"name": "Dell XPS 13 Laptop", "price_cents": 4500}  # $45 laptop = poisoned
    annotate_product(item)
    assert item["product_type"] == "laptop"
    assert item["price_anomaly"] == "underpriced"
