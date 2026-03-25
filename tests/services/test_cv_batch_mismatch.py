"""Tests for BasicCVTriage.analyze_batch() multi-image mismatch detection."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_analyze_batch_no_images():
    from src.app.services.cv_triage_basic import BasicCVTriage
    triage = BasicCVTriage()
    result = await triage.analyze_batch([])
    assert result["mismatch_detected"] is False
    assert result["fraud_score_delta"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_analyze_batch_single_image_no_mismatch():
    from src.app.services.cv_triage_basic import BasicCVTriage
    triage = BasicCVTriage()
    images = [{"bytes": None, "mime": "image/jpeg", "labels": ["laptop", "cracked screen"], "text": "ThinkPad X1", "filename": "laptop.jpg"}]
    result = await triage.analyze_batch(images, expected_product_type="laptop")
    assert result["mismatch_detected"] is False
    assert result["fraud_score_delta"] == 0
    assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_analyze_batch_cross_image_mismatch():
    """Apple (food) + laptop in same return submission → fraud signal."""
    from src.app.services.cv_triage_basic import BasicCVTriage
    triage = BasicCVTriage()
    images = [
        {"bytes": None, "mime": "image/jpeg", "labels": ["laptop", "keyboard"], "text": "", "filename": "laptop.jpg"},
        {"bytes": None, "mime": "image/jpeg", "labels": ["fruit", "apple", "food"], "text": "apple", "filename": "apple.jpg"},
    ]
    result = await triage.analyze_batch(images)
    assert result["mismatch_detected"] is True
    assert result["fraud_score_delta"] == 10
    assert len(result["product_types_found"]) >= 2


@pytest.mark.asyncio
async def test_analyze_batch_expected_product_mismatch():
    """Order says 'laptop' but CV sees 'phone' → delta 20."""
    from src.app.services.cv_triage_basic import BasicCVTriage
    triage = BasicCVTriage()
    images = [
        {"bytes": None, "mime": "image/jpeg", "labels": ["smartphone", "phone", "broken screen"], "text": "iPhone", "filename": "phone.jpg"},
    ]
    result = await triage.analyze_batch(images, expected_product_type="laptop")
    assert result["mismatch_detected"] is True
    assert result["fraud_score_delta"] == 20


@pytest.mark.asyncio
async def test_analyze_batch_accessory_no_mismatch():
    """Laptop + charger (accessory) should NOT trigger mismatch."""
    from src.app.services.cv_triage_basic import BasicCVTriage
    triage = BasicCVTriage()
    images = [
        {"bytes": None, "mime": "image/jpeg", "labels": ["laptop", "notebook"], "text": "", "filename": "laptop.jpg"},
        {"bytes": None, "mime": "image/jpeg", "labels": ["charger", "cable", "adapter"], "text": "", "filename": "charger.jpg"},
    ]
    result = await triage.analyze_batch(images, expected_product_type="laptop")
    assert result["mismatch_detected"] is False


def test_detect_product_type_laptop():
    from src.app.services.cv_triage_basic import BasicCVTriage
    triage = BasicCVTriage()
    assert triage._detect_product_type(["ThinkPad", "laptop"], "", None) == "laptop"


def test_detect_product_type_food():
    from src.app.services.cv_triage_basic import BasicCVTriage
    triage = BasicCVTriage()
    assert triage._detect_product_type(["apple", "fruit"], "green apple", None) == "food"
