import base64
import os

from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


def test_returns_submit_applies_multi_image_mismatch_signal(monkeypatch, tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/returns_multi.sqlite"
    app = create_app()
    client = TestClient(app, headers=default_headers())

    async def _fake_analyze_batch(self, images, *, expected_product_type=None):
        assert len(images) == 2
        return {
            "results": [],
            "mismatch_detected": True,
            "fraud_score_delta": 10,
            "mismatch_detail": "Multiple product types in evidence rail: laptop, food",
            "product_types_found": ["laptop", "food"],
        }

    monkeypatch.setattr(
        "src.app.services.cv_triage_basic.BasicCVTriage.analyze_batch",
        _fake_analyze_batch,
        raising=True,
    )

    payload = {
        "sku": "LAPTOP-OK",
        "uid": "u-multi-1",
        "images": [
            {"filename": "laptop.jpg", "b64": base64.b64encode(b"img-one").decode("ascii")},
            {"filename": "apple.jpg", "b64": base64.b64encode(b"img-two").decode("ascii")},
        ],
        "description": "return",
    }
    resp = client.post("/api/v1/returns/submit", json=payload)
    assert resp.status_code == 200

    body = resp.json()
    signals = body.get("score", {}).get("signals", [])
    assert any(s.get("signal") == "multi_image_mismatch" and s.get("delta") == 10 for s in signals)
