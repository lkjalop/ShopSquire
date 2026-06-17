"""Cross-modal (vision ⟂ NLP) brand-consistency check: text brand vs image brand."""
from __future__ import annotations

from src.app.routers.recommend import _cross_modal_brand_conflict_question as conflict


def test_text_asus_image_msi_raises_conflict():
    note, q = conflict(["asus"], "msi")
    assert note is not None and "ASUS" in note and "MSI" in note
    assert q["source"] == "image_text_brand_conflict"
    labels = " ".join(o["label"] for o in q["options"]).lower()
    assert "keep" in labels and "match the image" in labels and "compare" in labels


def test_matching_brand_no_conflict():
    assert conflict(["msi"], "msi") == (None, None)
    assert conflict(["apple"], "apple") == (None, None)


def test_no_image_brand_no_conflict():
    assert conflict(["asus"], None) == (None, None)
    assert conflict(["asus"], "") == (None, None)


def test_no_text_brand_no_conflict():
    # Image-only request (no text brand) is NOT a conflict — image brand is authoritative.
    assert conflict([], "msi") == (None, None)
    assert conflict(None, "msi") == (None, None)


def test_keeps_text_brand_not_image():
    # Policy: never auto-switch. The note must say we KEPT the text brand.
    note, _ = conflict(["dell"], "apple")
    assert "kept your Dell" in note.lower() or "kept your dell" in note.lower()


def test_never_raises_on_bad_input():
    assert conflict("garbage", 123) == (None, None) or isinstance(conflict("garbage", 123), tuple)
