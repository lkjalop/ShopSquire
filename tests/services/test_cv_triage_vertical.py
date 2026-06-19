"""Tests proving cv_triage_basic uses profile-backed relevance tokens."""
import json
import asyncio
import pytest
from unittest.mock import patch

# ─── Helpers ────────────────────────────────────────────────────────────────

_PHARMACY_PROFILE = {
    "id": "pharmacy",
    "relevant_image_tokens": [
        "medicine", "pill", "capsule", "bottle", "pharmacy", "supplement",
        "vitamin", "cream", "ointment", "inhaler", "syringe", "bandage",
    ],
    "off_topic_image_tokens": [
        "laptop", "computer", "gpu", "keyboard", "mouse", "monitor", "gaming",
    ],
}

_FASHION_PROFILE = {
    "id": "fashion",
    "relevant_image_tokens": [
        "shirt", "dress", "shoes", "sneakers", "boots", "jacket", "coat",
        "pants", "jeans", "skirt", "nike", "adidas", "clothing",
    ],
    "off_topic_image_tokens": [
        "laptop", "computer", "gpu", "keyboard", "mouse", "monitor", "gaming",
        "medicine", "pill", "capsule", "pharmacy", "syringe",
    ],
}


def _run_triage(profile_data: dict, labels: list, text: str = ""):
    """Import and call BasicCVTriage.analyze with a mocked store profile."""
    from src.app.services.cv_triage_basic import BasicCVTriage

    triage = BasicCVTriage()
    with patch(
        "src.app.platform.store_profile.get_store_profile",
        return_value=profile_data,
    ):
        result = asyncio.get_event_loop().run_until_complete(
            triage.analyze(labels=labels, extracted_text=text)
        )
    return result


# ─── Pharmacy vertical ──────────────────────────────────────────────────────

class TestPharmacyImageRelevance:
    def test_medicine_bottle_is_relevant(self):
        r = _run_triage(_PHARMACY_PROFILE, ["bottle", "label"])
        assert r["image_relevance"] == "relevant"

    def test_pill_capsule_is_relevant(self):
        r = _run_triage(_PHARMACY_PROFILE, ["capsule"])
        assert r["image_relevance"] == "relevant"

    def test_laptop_image_is_offtopic(self):
        r = _run_triage(_PHARMACY_PROFILE, ["laptop", "keyboard"])
        assert r["image_relevance"] == "off_topic"

    def test_no_labels_benefit_of_doubt(self):
        r = _run_triage(_PHARMACY_PROFILE, [])
        assert r["image_relevance"] == "relevant"


# ─── Fashion vertical ───────────────────────────────────────────────────────

class TestFashionImageRelevance:
    def test_sneakers_is_relevant(self):
        r = _run_triage(_FASHION_PROFILE, ["sneakers", "shoe"])
        assert r["image_relevance"] == "relevant"

    def test_dress_is_relevant(self):
        r = _run_triage(_FASHION_PROFILE, ["dress", "clothing"])
        assert r["image_relevance"] == "relevant"

    def test_laptop_is_offtopic(self):
        r = _run_triage(_FASHION_PROFILE, ["laptop", "monitor"])
        assert r["image_relevance"] == "off_topic"

    def test_medicine_is_offtopic(self):
        r = _run_triage(_FASHION_PROFILE, ["pill", "capsule"])
        assert r["image_relevance"] == "off_topic"

    def test_no_labels_benefit_of_doubt(self):
        r = _run_triage(_FASHION_PROFILE, [])
        assert r["image_relevance"] == "relevant"
