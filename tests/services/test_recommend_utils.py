"""recommend_utils service — shared pure leaf utilities (core/adapter split foundation).

Parity: the router re-exports these, so the same object must be reachable from both modules,
and behaviour must be unchanged after extraction.
"""
from __future__ import annotations

import contextlib

from src.app.services.recommend_utils import (
    _brand_display_name,
    _candidate_matches_brand,
    _extract_candidate_numeric_specs,
    _result_price_dollars,
)


@contextlib.contextmanager
def _vertical(profile_id: str):
    from src.app.platform.store_profile import reset_active_profile_id, set_active_profile_id

    token = set_active_profile_id(profile_id)
    try:
        yield
    finally:
        reset_active_profile_id(token)


def test_candidate_matches_brand_alias_and_direct():
    assert _candidate_matches_brand({"name": "MacBook Pro 16"}, ["apple"]) is True
    assert _candidate_matches_brand({"name": "Legion 5 Pro"}, ["lenovo"]) is True
    assert _candidate_matches_brand({"sku": "ROG-STRIX-1"}, ["asus"]) is True
    assert _candidate_matches_brand({"name": "ThinkPad X1"}, ["dell"]) is False


def test_candidate_matches_brand_uses_active_profile_no_bleed():
    with _vertical("pharmacy"):
        assert _candidate_matches_brand({"name": "Panadol Osteo 96 Tablets"}, ["panadol"]) is True
        assert _candidate_matches_brand({"name": "ROG Zephyrus Laptop"}, ["asus"]) is False


def test_candidate_matches_brand_empty_inputs():
    assert _candidate_matches_brand(None, ["apple"]) is False
    assert _candidate_matches_brand({"name": "MacBook"}, None) is False
    assert _candidate_matches_brand({"name": "MacBook"}, []) is False


def test_brand_display_name_known_and_fallback():
    assert _brand_display_name("asus") == "ASUS"
    assert _brand_display_name("microsoft") == "Microsoft Surface"
    assert _brand_display_name("framework") == "Framework"  # capitalize fallback
    assert _brand_display_name(None) == ""
    assert _brand_display_name("") == ""


def test_brand_display_name_uses_active_profile():
    with _vertical("pharmacy"):
        assert _brand_display_name("panadol") == "Panadol"
        assert _brand_display_name("asus") == "Asus"


def test_result_price_dollars_prefers_price_then_cents():
    assert _result_price_dollars({"price": 1499.0}) == 1499.0
    assert _result_price_dollars({"price_cents": 149900}) == 1499.0
    assert _result_price_dollars({"price": 0, "price_cents": 99900}) == 999.0
    assert _result_price_dollars({"price": -5, "price_cents": 0}) is None
    assert _result_price_dollars(None) is None


def test_extract_candidate_numeric_specs_from_structured_specs():
    out = _extract_candidate_numeric_specs(
        {"name": "Legion 5", "specs": {"ram_gb": 16, "storage_gb": 512, "gpu": "RTX 4060"}}
    )
    assert out["ram_gb"] == 16.0
    assert out["storage_gb"] == 512.0
    assert out["has_dedicated_gpu"] is True
    assert out["gaming_style"] is True  # "legion" in text


def test_extract_candidate_numeric_specs_parses_from_name_text():
    out = _extract_candidate_numeric_specs({"name": "Office Ultrabook 16GB RAM 512GB 14 inch"})
    assert out["ram_gb"] == 16.0
    assert out["storage_gb"] == 512.0
    assert out["display_inches"] == 14.0
    assert out["portable"] is True  # ultrabook + <=14.5"
    assert out["has_dedicated_gpu"] is False


def test_extract_candidate_numeric_specs_empty():
    out = _extract_candidate_numeric_specs({})
    assert out["ram_gb"] is None
    assert out["has_dedicated_gpu"] is False


def test_router_reexports_same_objects():
    # Foundation invariant: the router shim re-exports the identical functions (no copies).
    from src.app.routers import recommend as r

    assert r._candidate_matches_brand is _candidate_matches_brand
    assert r._brand_display_name is _brand_display_name
    assert r._result_price_dollars is _result_price_dollars
    assert r._extract_candidate_numeric_specs is _extract_candidate_numeric_specs
