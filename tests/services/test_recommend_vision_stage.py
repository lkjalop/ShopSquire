"""recommend_vision_stage — extracted vision decision primitives (core/adapter split, P2).

Pure cross-modal brand-conflict + supported-brand-hint resolution. Locks behaviour + re-export
identity (the router shim must be the SAME objects, not copies).
"""
from __future__ import annotations

from src.app.services.recommend_vision_stage import (
    _cross_modal_brand_conflict_question,
    _resolve_supported_brand_hint,
)


def test_cross_modal_conflict_detected():
    note, q = _cross_modal_brand_conflict_question(["asus"], "msi")
    assert note and "ASUS" in note and "MSI" in note
    assert q["id"] == "ask_image_text_brand_conflict"
    assert q["priority"] == 0


def test_cross_modal_no_conflict_when_aligned_or_missing():
    assert _cross_modal_brand_conflict_question(["asus"], "asus") == (None, None)  # aligned
    assert _cross_modal_brand_conflict_question([], "msi") == (None, None)          # no text brand
    assert _cross_modal_brand_conflict_question(["asus"], None) == (None, None)     # no image brand


def test_resolve_supported_brand_hint_precedence():
    assert _resolve_supported_brand_hint("asus") == "asus"                          # explicit
    assert _resolve_supported_brand_hint(None, {"_request_brand_hint": "dell"}) == "dell"
    assert _resolve_supported_brand_hint(None, {"brands": ["hp"]}) == "hp"
    assert _resolve_supported_brand_hint(None, None, "I want a macbook") == "apple"  # query token
    assert _resolve_supported_brand_hint(None, None, "a lenovo please") == "lenovo"
    assert _resolve_supported_brand_hint(None, None, "just a laptop") == ""          # none


def test_router_reexports_same_objects():
    from src.app.routers import recommend as r

    assert r._cross_modal_brand_conflict_question is _cross_modal_brand_conflict_question
    assert r._resolve_supported_brand_hint is _resolve_supported_brand_hint
