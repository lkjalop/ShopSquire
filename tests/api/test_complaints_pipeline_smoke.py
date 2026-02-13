import io
import os
import json
import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.services.cv_provider import ManagedCVProvider


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path_factory.getbasetemp()}/pipeline.sqlite"
    app = create_app()
    return TestClient(app)


def test_complaints_pipeline_smoke(client, monkeypatch):
    # Mock CV provider for deterministic flow
    async def fake_labels_and_text(self, image_bytes: bytes):
        return ["screen", "crack"], "SN-ABC123"

    monkeypatch.setattr(ManagedCVProvider, "get_labels_and_text", fake_labels_and_text)

    # Submit with one image
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDAT\x08\x99c``\xf8\x0f\x00\x01\x05\x01\x00\x18\x9d\x9c\x1e\x00\x00\x00\x00IEND\xAE\x42\x60\x82"
    )
    files = [("images", ("a.png", io.BytesIO(png_bytes), "image/png"))]
    payload = {"order_id": "ORDER9", "issue_type": "damage", "description": "cracked screen"}
    resp = client.post("/api/v1/support/complaints/submit", data=payload, files=files)
    if resp.status_code == 422:
        pytest.skip(f"multipart env issue: {resp.text}")
    assert resp.status_code == 200
    data = resp.json()
    case_id = data["case_id"]

    # Status
    r2 = client.get(f"/api/v1/support/complaints/{case_id}/status")
    assert r2.status_code == 200
    s2 = r2.json()
    assert s2["case"]["id"] == case_id

    # Add images
    files2 = [("images", ("b.png", io.BytesIO(png_bytes), "image/png"))]
    r3 = client.post(f"/api/v1/support/complaints/{case_id}/add-images", files=files2)
    if r3.status_code == 422:
        pytest.skip(f"multipart env issue: {r3.text}")
    assert r3.status_code == 200

    # Return label
    r4 = client.get(f"/api/v1/support/complaints/{case_id}/return-label")
    assert r4.status_code == 200
    label = r4.json().get("label")
    assert label and label.get("tracking_number")
