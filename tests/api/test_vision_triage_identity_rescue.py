from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from src.app.main import create_app


_PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
)


def test_vision_triage_stage_b_identity_rescue_for_weak_labels(monkeypatch):
    import src.app.routers.vision as vision
    import src.app.services.product_identity_agent as pia

    async def _fake_labels_and_text(self, _blob: bytes, mode: str = "visual_search"):
        return ["ms texti"], "", None

    def _fake_analyze(self, _labels, _text):
        return {"damage_type": "unknown", "severity": "undetermined", "confidence": 0.2}

    def _fake_identity_from_text(*args, **kwargs):
        return {
            "ok": True,
            "identified": False,
            "brand": None,
            "model": None,
            "product_type": "unknown",
            "confidence": 0.0,
        }

    def _fake_identity_from_image(*args, **kwargs):
        return {
            "ok": True,
            "identified": True,
            "brand": "MSI",
            "model": "Thin A15",
            "product_type": "laptop",
            "confidence": 0.74,
        }

    monkeypatch.setattr(vision.ManagedCVProvider, "get_labels_and_text", _fake_labels_and_text)
    monkeypatch.setattr(vision.BasicCVTriage, "analyze", _fake_analyze)
    monkeypatch.setattr(pia, "identify_product_from_text", _fake_identity_from_text)
    monkeypatch.setattr(pia, "identify_product_from_image", _fake_identity_from_image)

    client = TestClient(create_app())
    files = {"image": ("ms-texti.png", _PNG_1X1, "image/png")}
    r = client.post("/api/v1/vision/triage", headers={"x-api-key": "local-merchant-key"}, files=files)
    assert r.status_code == 200, r.text
    body = r.json()
    prod = body.get("product_identity") or {}
    assert prod.get("brand") == "MSI", body
    assert str(prod.get("source") or "") == "vision_stage_b", body

