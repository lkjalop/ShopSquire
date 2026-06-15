"""Step B — product captioner (schema-safe compose + cached + fail-open)."""
from __future__ import annotations

import src.app.services.product_captioner as pc
import src.app.services.vision_cache as vc


def test_compose_from_structured_identity():
    ident = {"identified": True, "brand": "MSI", "model": "Katana 15", "product_type": "laptop",
             "form_factor": "clamshell", "gpu_hint": "RTX 4070", "display_inches_hint": 15, "ram_gb_hint": 16}
    cap = pc.compose_caption(ident)
    assert "MSI" in cap and "Katana 15" in cap and "laptop" in cap
    assert "GPU RTX 4070" in cap and '15" display' in cap and "16GB RAM" in cap


def test_compose_skips_unknown_and_integrated():
    ident = {"identified": True, "brand": "Dell", "model": "unknown", "gpu_hint": "integrated", "product_type": "laptop"}
    cap = pc.compose_caption(ident)
    assert "Dell" in cap and "laptop" in cap
    assert "unknown" not in cap.lower() and "integrated" not in cap.lower()


def test_compose_empty_when_not_identified():
    assert pc.compose_caption({"identified": False, "brand": "X"}) == ""
    assert pc.compose_caption(None) == ""


def test_caption_product_caches_and_fail_open(monkeypatch):
    vc.clear()
    calls = {"n": 0}

    def fake_identify(image_bytes, **k):
        calls["n"] += 1
        return {"identified": True, "brand": "MSI", "product_type": "laptop"}

    import src.app.services.product_identity_agent as pia
    monkeypatch.setattr(pia, "identify_product_from_image", fake_identify)

    img = b"img-bytes-1"
    c1 = pc.caption_product(img)
    c2 = pc.caption_product(img)
    assert "MSI" in c1 and "laptop" in c1
    assert c2 == c1
    assert calls["n"] == 1  # second served from caption cache


def test_caption_product_empty_image():
    assert pc.caption_product(b"") == ""
