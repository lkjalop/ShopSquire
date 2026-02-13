import os
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images"


def test_cv_upload_receipt_fixture_sets_invoice_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path}/cv_upload.sqlite")
    monkeypatch.setenv("CV_OCR_PROVIDER", "embedded")
    app = create_app()
    client = TestClient(app, headers=default_headers())

    receipt = (FIXTURE_DIR / "return_wrong_receipt.png").read_bytes()
    files = {"image": ("receipt.png", receipt, "image/png")}

    r = client.post("/api/v1/cv/upload", files=files, data={"nonce": ""})
    assert r.status_code == 200, r.text
    body = r.json()
    t2 = body.get("cv_tier2") or {}
    ocr = (t2.get("ocr") or {}).get("text") or ""
    assert "RECEIPT" in ocr.upper()
    tags = t2.get("evidence_tags") or []
    assert "invoice_mismatch" in tags
