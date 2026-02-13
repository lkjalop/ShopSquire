import os
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers
from src.app.services.returns import ocr_image_bytes


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images"


def test_cv_analyze_accepts_fixture_extracted_text(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/cv.sqlite"
    app = create_app()
    client = TestClient(app, headers=default_headers())

    img_bytes = (FIXTURE_DIR / "return_wrong_phone.png").read_bytes()
    extracted = ocr_image_bytes(img_bytes)
    assert extracted, "Expected embedded OCR text in fixture"

    payload = {
        "labels": ["phone", "device"],
        "extracted_text": extracted,
        "provider": "basic",
        "model": "cv_triage_basic",
        "description": "fixture",
    }
    r = client.post("/api/v1/cv/analyze", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert "cv_analysis" in body
    assert extracted[:10].lower() in (body["cv_analysis"].get("extracted_text") or "").lower()
