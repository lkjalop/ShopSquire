"""recommend_utils service — shared pure leaf utilities (core/adapter split foundation).

Parity: the router re-exports these, so the same object must be reachable from both modules,
and behaviour must be unchanged after extraction.
"""
from __future__ import annotations

from src.app.services.recommend_utils import (
    _brand_display_name,
    _candidate_matches_brand,
    _result_price_dollars,
)


def test_candidate_matches_brand_alias_and_direct():
    assert _candidate_matches_brand({"name": "MacBook Pro 16"}, ["apple"]) is True
    assert _candidate_matches_brand({"name": "Legion 5 Pro"}, ["lenovo"]) is True
    assert _candidate_matches_brand({"sku": "ROG-STRIX-1"}, ["asus"]) is True
    assert _candidate_matches_brand({"name": "ThinkPad X1"}, ["dell"]) is False


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


def test_result_price_dollars_prefers_price_then_cents():
    assert _result_price_dollars({"price": 1499.0}) == 1499.0
    assert _result_price_dollars({"price_cents": 149900}) == 1499.0
    assert _result_price_dollars({"price": 0, "price_cents": 99900}) == 999.0
    assert _result_price_dollars({"price": -5, "price_cents": 0}) is None
    assert _result_price_dollars(None) is None


def test_router_reexports_same_objects():
    # Foundation invariant: the router shim re-exports the identical functions (no copies).
    from src.app.routers import recommend as r

    assert r._candidate_matches_brand is _candidate_matches_brand
    assert r._brand_display_name is _brand_display_name
    assert r._result_price_dollars is _result_price_dollars
