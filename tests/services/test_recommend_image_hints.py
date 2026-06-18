"""recommend_image_hints service — the extracted image-hint stage (core/adapter split).

CORE: labels/CV-signals → bounded safe brand/category/use-case hints. ADAPTER: brand patterns
from the StoreProfile. Security invariant: unsafe CV signals (OCR/QR/PII) put the image
'under_review' and never become a ranking signal.
"""
from __future__ import annotations

from src.app.services.recommend_image_hints import (
    _brand_label_patterns,
    _safe_image_hints_for_fast_path,
    _UNSAFE_IMAGE_SIGNAL_KEYS,
)


def _hints(labels=None, query="", cv=None, product_identity=None):
    ctx = {"labels": labels or []}
    if product_identity is not None:
        ctx["product_identity"] = product_identity
    return _safe_image_hints_for_fast_path(image_context=ctx, image_cv_signals=cv or {}, query=query)


def test_asus_image_yields_asus_brand_hint():
    h = _hints(labels=["asus", "rog", "laptop"], query="gaming laptop")
    assert "asus" in h["brand_hints"]
    assert "laptop" in h["category_hints"]
    assert h["trust_state"] == "trusted"


def test_macbook_maps_to_apple():
    h = _hints(labels=["macbook"], query="")
    assert "apple" in h["brand_hints"]  # macbook normalises to apple


def test_msi_via_product_identity():
    h = _hints(query="laptop", product_identity={"brand": "msi", "product_type": "laptop"})
    assert "msi" in h["brand_hints"]


def test_unrelated_image_yields_no_brand_hint():
    h = _hints(labels=["banana", "fruit"], query="gaming laptop")
    assert h["brand_hints"] == []  # off-topic image contributes no brand steer


def test_unsafe_signals_force_under_review_and_drop_payloads():
    h = _hints(labels=["laptop"], query="laptop", cv={"qr_prompt_injection": True, "ssn_detected": True})
    assert h["trust_state"] == "under_review"
    assert h["unsafe_flags"]["qr_prompt_injection"] is True
    # the untrusted CV payload fields are reported as dropped, never surfaced as hints:
    assert set(h["dropped_fields"]) == set(_UNSAFE_IMAGE_SIGNAL_KEYS)


def test_gaming_use_case_hint_from_spec_tokens():
    h = _hints(labels=["rtx", "4070"], query="rtx 4070 144hz")
    assert "gaming" in h["use_case_hints"]
    assert "laptop" in h["category_hints"]


def test_brand_patterns_come_from_profile():
    pats = _brand_label_patterns()
    assert "lenovo" in pats and "thinkpad" in pats["lenovo"]
