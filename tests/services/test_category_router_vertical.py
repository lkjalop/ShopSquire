"""category_router entity-NER is PER-REQUEST profile-scoped — no electronics bleed.

category_router is a vertical-blind CORE mechanism: it detects category/brand/use-case/spec
from the ACTIVE StoreProfile's patterns. Electronics keeps its exact behaviour (entity_* slots
in electronics.json, excised verbatim from the old hardcoded dicts); fashion/pharmacy derive
their patterns from their own manufacturers / use_case_patterns / product_type_rules, so an
electronics-flavoured query under a non-electronics tenant yields NO electronics brands or
use-cases.
"""
from __future__ import annotations

import contextlib

from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id
from src.app.services import category_router as cr


@contextlib.contextmanager
def _vertical(pid: str):
    token = set_active_profile_id(pid)
    cr.reset_cache()
    try:
        yield
    finally:
        reset_active_profile_id(token)
        cr.reset_cache()


def test_electronics_detects_brand_use_case_category():
    with _vertical("electronics"):
        e = cr.detect_entities("gaming laptop rtx 4070 macbook 16gb ram")
        assert "nvidia" in e["brands"] and "apple" in e["brands"]
        assert "gaming" in e["use_cases"]
        assert any(c["slug"] == "laptop" for c in e["categories"])
        assert e["specs"].get("ram", {}).get("value") == "16"


def test_fashion_no_electronics_bleed():
    with _vertical("fashion"):
        e = cr.detect_entities("gaming laptop rtx 4070 macbook thinkpad")
        # zero electronics brands / use-cases leak into a fashion tenant
        assert e["brands"] == []
        assert "gaming" not in e["use_cases"] and "video_editing" not in e["use_cases"]
        assert not any(c["slug"] == "laptop" for c in e["categories"])


def test_fashion_detects_its_own_brand_and_category():
    with _vertical("fashion"):
        e = cr.detect_entities("nike air max running shoes for the gym")
        assert "nike" in e["brands"]
        assert any(c["slug"] == "shoes" for c in e["categories"])


def test_pharmacy_no_electronics_bleed():
    with _vertical("pharmacy"):
        e = cr.detect_entities("macbook pro thinkpad rtx gaming laptop")
        assert e["brands"] == []
        assert e["use_cases"] == [] or "gaming" not in e["use_cases"]
        assert not any(c["slug"] == "laptop" for c in e["categories"])


def test_category_detection_is_profile_scoped():
    # "laptop" is an electronics category; a fashion tenant must not classify it as such.
    with _vertical("electronics"):
        assert cr.detect_category("gaming laptop") == "laptop"
    with _vertical("fashion"):
        assert cr.detect_category("gaming laptop") != "laptop"
