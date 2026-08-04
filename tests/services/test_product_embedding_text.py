"""Step A — canonical product embedding text (fixes the SKU-only embedding bug)."""
from __future__ import annotations

from src.app.services.product_embedding_text import build_embedding_text


def test_rich_text_from_dict():
    p = {"name": "MSI Katana 15", "brand": "MSI", "category": "laptop",
         "specs": {"gpu": "RTX 4070", "ram_gb": 16, "display_hz": 144}, "sku": "GAM-1"}
    t = build_embedding_text(p)
    assert "MSI Katana 15" in t
    assert "MSI laptop" in t
    assert "gpu: RTX 4070" in t and "ram gb: 16" in t


def test_caption_appended_for_multimodal():
    t = build_embedding_text({"name": "X", "sku": "S1"}, caption="black 16-inch gaming laptop, RGB keyboard")
    assert "black 16-inch gaming laptop, RGB keyboard" in t


def test_specs_accepts_json_string():
    assert "gpu: RTX 4060" in build_embedding_text({"name": "Y", "specs": '{"gpu": "RTX 4060"}', "sku": "S2"})


def test_fallback_to_sku_then_empty():
    assert build_embedding_text({"sku": "ONLY-SKU"}) == "ONLY-SKU"
    assert build_embedding_text({}) == ""


def test_object_access_not_just_dict():
    class P:
        name = "Dell XPS 15"; brand = "Dell"; sku = "D1"; specs = None; category = None
    t = build_embedding_text(P())
    assert "Dell XPS 15" in t and "Dell" in t


def test_bool_specs_only_true_flags():
    t = build_embedding_text({"name": "Z", "specs": {"touchscreen": True, "backlit": False}, "sku": "S3"})
    assert "touchscreen" in t and "backlit" not in t


def test_not_just_sku_when_details_present():
    # Regression guard for the original bug: rich product != bare SKU.
    p = {"name": "HP Victus 16", "specs": {"gpu": "RTX 4060"}, "sku": "GAM-2"}
    t = build_embedding_text(p)
    assert t != "GAM-2" and "HP Victus 16" in t
