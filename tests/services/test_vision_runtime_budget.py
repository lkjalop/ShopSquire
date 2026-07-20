from __future__ import annotations

import asyncio
import base64

import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.routers.vision import _needs_damage_reasoning
from src.app.services.cv_provider import ManagedCVProvider


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
)


def test_damage_reasoning_is_selective():
    assert not _needs_damage_reasoning(["laptop", "lenovo"], "ThinkPad X1", "product.jpg")
    assert _needs_damage_reasoning(["laptop", "cracked screen"], "", "damage.jpg")
    assert _needs_damage_reasoning(["laptop"], "", "warranty-return.png")


@pytest.mark.asyncio
async def test_visual_search_does_not_launch_unbounded_local_ocr_fallback(monkeypatch):
    monkeypatch.setenv("CV_PROVIDER", "none")
    monkeypatch.delenv("CV_VISUAL_SEARCH_OCR_FALLBACK", raising=False)
    provider = ManagedCVProvider()

    def _unexpected_ocr(_blob):
        raise AssertionError("visual-search fallback OCR must remain deferred")

    monkeypatch.setattr(provider, "_tesseract_text", _unexpected_ocr)
    labels, text, identity = await provider.get_labels_and_text(b"not-an-image", mode="visual_search")
    assert (labels, text, identity) == ([], "", None)
    assert provider.last_ocr_meta["cv_extraction_method"] == "visual_search_ocr_deferred"


def test_provider_timeout_is_degradation_not_security_risk(monkeypatch):
    import src.app.routers.vision as vision
    import src.app.services.product_identity_agent as identity

    async def _slow_provider(self, _blob, mode="visual_search"):
        await asyncio.sleep(0.1)
        return ["laptop"], "", None

    def _basic_analysis(self, _labels, _text, **_kwargs):
        return {"damage_type": "unknown", "severity": "undetermined", "confidence": 0.2}

    monkeypatch.setenv("CV_PROVIDER_TOTAL_TIMEOUT_S", "0.01")
    monkeypatch.setattr(vision.ManagedCVProvider, "get_labels_and_text", _slow_provider)
    monkeypatch.setattr(vision.BasicCVTriage, "analyze", _basic_analysis)
    monkeypatch.setattr(identity, "identify_product_from_text",
                        lambda **_kwargs: {"identified": False})
    monkeypatch.setattr(identity, "identify_product_from_image",
                        lambda *_args, **_kwargs: {"identified": False})

    client = TestClient(create_app())
    response = client.post(
        "/api/v1/vision/triage",
        headers={"x-api-key": "local-merchant-key"},
        files={"image": ("plain-product.png", _PNG_1X1, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis_state"]["analysis_degraded"] is True
    assert "vision_provider_timeout" in body["analysis_state"]["degraded_reasons"]
    assert body["analysis_state"]["security_risk"] is False
    assert body["security"]["clean"] is True
