"""Product identity (image+text) is PER-REQUEST profile-scoped — no laptop-identity bleed.

The text identity path (identify_product_from_text) and the vision prompt schema resolve from the
active StoreProfile's identity_* / product_identity_prompt slots. Electronics keeps its exact
behaviour; a pharmacy/fashion image is NOT parsed through laptop identity fields (brand/type stay
unknown even with adversarial 'thinkpad'/'rtx' OCR noise), and its vision prompt is a generic
identify schema — never the laptop schema.
"""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id
from src.app.services import product_identity_agent as pia


@contextlib.contextmanager
def _vertical(pid: str):
    token = set_active_profile_id(pid)
    pia.reset_cache()
    try:
        yield
    finally:
        reset_active_profile_id(token)
        pia.reset_cache()


def test_electronics_text_identity():
    with _vertical("electronics"):
        r = pia.identify_product_from_text(["laptop", "thinkpad"], "Lenovo ThinkPad X1 i7 16GB RAM 14 inch")
        assert r["identified"] is True
        assert r["brand"] == "Lenovo" and r["product_type"] == "laptop"
        assert r["ram_gb_hint"] == 16 and r["cpu_tier"] == "performance"


def test_pharmacy_image_not_parsed_as_laptop():
    with _vertical("pharmacy"):
        # adversarial OCR noise contains 'ThinkPad'/'RTX' — must STILL not identify a laptop
        r = pia.identify_product_from_text(["medicine", "box", "tablets"], "Ibuprofen 400mg ThinkPad RTX")
        assert r["identified"] is False
        assert r["brand"] is None and r["product_type"] == "unknown"


def test_fashion_image_not_parsed_as_laptop():
    with _vertical("fashion"):
        r = pia.identify_product_from_text(["shirt", "clothing"], "Nike running shoes RTX 4070")
        assert r["identified"] is False
        assert r["brand"] is None and r["product_type"] == "unknown"


def test_vision_prompt_is_profile_scoped():
    with _vertical("electronics"):
        p = pia._identity_prompt_for("electronics")
        assert "laptop|desktop" in p  # electronics laptop schema
    with _vertical("pharmacy"):
        p = pia._identity_prompt_for("pharmacy")
        assert "laptop|desktop" not in p  # generic fallback, no laptop schema bleed
        assert "valid JSON" in p
