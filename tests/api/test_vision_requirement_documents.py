from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_plain_text_requirements_use_the_same_read_only_evidence_boundary(monkeypatch):
    import src.app.routers.vision as vision

    monkeypatch.setattr(vision, "_persist_artifact_verdict", lambda **kwargs: {
        "artifact_id": kwargs["artifact_id"], "sha256": kwargs["sha256"],
        "verdict_version": 1, "state": kwargs["state"], "authority": "read_only",
    })
    content = (
        b"RAM 32GB minimum\nStorage 1TB NVMe\n"
        b"Windows 11 Pro recommended\nGPU VRAM 16GB acceptable alternative"
    )
    response = TestClient(create_app()).post(
        "/api/v1/vision/triage?extract_text=1",
        headers={"x-api-key": "local-merchant-key"},
        files={"image": ("requirements.txt", content, "text/plain")},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["extracted_text"] == content.decode("utf-8")
    assert payload["artifact"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert payload["artifact"]["state"] == "clean"
    assert payload["artifact"]["authority"] == "read_only"
    assert payload["security"]["commercial_authority"] == "read_only"


def test_binary_content_disguised_as_text_is_rejected():
    response = TestClient(create_app()).post(
        "/api/v1/vision/triage?extract_text=1",
        headers={"x-api-key": "local-merchant-key"},
        files={"image": ("requirements.txt", b"RAM 32GB\x00\x00binary", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "document_conversion_failed"
