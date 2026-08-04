"""Unit tests for the VLM/OCR image-size gate (image_downscale)."""
from __future__ import annotations

import io

import pytest

from src.app.services import image_downscale as D


def _png(w: int, h: int) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (123, 200, 50)).save(buf, format="PNG")
    return buf.getvalue()


def test_small_image_passes_through_unchanged():
    blob = _png(225, 225)
    out = D.bound_image_for_vlm(blob)
    assert out["reject"] is False
    assert out["downscaled"] is False
    assert out["bytes"] is blob  # identity — not re-encoded


def test_large_dimensions_are_downscaled_for_vlm():
    blob = _png(2000, 2000)  # 4 MP — the size that hung the VLM
    out = D.bound_image_for_vlm(blob, max_edge=1280)
    assert out["reject"] is False
    assert out["downscaled"] is True
    # longest edge capped -> pixel count (the thing that drives VLM cost) collapses.
    # (byte size can rise for a solid-colour synthetic PNG re-encoded as JPEG — pixels are the invariant)
    dw, dh = out["meta"]["downscaled_to"]
    assert max(dw, dh) <= 1280
    assert dw * dh <= (2000 * 2000) // 2  # at least halved


def test_downscale_preserves_original_input():
    blob = _png(2000, 2000)
    original = bytes(blob)
    D.bound_image_for_vlm(blob)
    assert blob == original  # never mutates the caller's bytes (steg needs them intact)


def test_reject_by_megapixels(monkeypatch):
    monkeypatch.setattr(D, "MAX_MEGAPIXELS", 5)
    blob = _png(3000, 3000)  # 9 MP > 5
    out = D.bound_image_for_vlm(blob)
    assert out["reject"] is True
    assert out["reason"] == "megapixels"


def test_reject_by_bytes_even_when_unreadable(monkeypatch):
    monkeypatch.setattr(D, "MAX_BYTES", 100)
    out = D.bound_image_for_vlm(b"\x00" * 500)  # not a real image, but > byte cap
    assert out["reject"] is True
    assert out["reason"] == "bytes"


def test_unreadable_small_blob_is_rejected():
    out = D.bound_image_for_vlm(b"not-an-image")
    assert out["reject"] is True
    assert out["reason"] == "decode"
    assert out["meta"]["readable"] is False


def test_size_class_bands(monkeypatch):
    monkeypatch.setattr(D, "WARN_MEGAPIXELS", 2)
    monkeypatch.setattr(D, "MAX_MEGAPIXELS", 30)
    assert D.size_class(_png(225, 225))["verdict"] == "ok"
    assert D.size_class(_png(2000, 2000))["verdict"] == "warn"   # 4 MP > warn(2), < max(30)


def test_real_fixtures_are_bounded():
    """The exact files that hung triage must now be downscaled (or rejected), never pass-through."""
    import os
    for path in ["dump/test-cv/Dell 15 DC15255.webp",
                 "dump/test-sec/steg-prompt_injection_hidden-Dell_15_DC15255.png"]:
        if not os.path.exists(path):
            pytest.skip(f"fixture missing: {path}")
        out = D.bound_image_for_vlm(open(path, "rb").read())
        assert out["reject"] is False
        assert out["downscaled"] is True, f"{path} should be downscaled for the VLM"
