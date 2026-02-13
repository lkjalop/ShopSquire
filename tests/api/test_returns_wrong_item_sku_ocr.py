import base64
import os
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images"


def test_returns_flags_ocr_sku_mismatch_from_fixture(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/returns.sqlite"
    app = create_app()
    client = TestClient(app, headers=default_headers())

    wrong_sku_img = (FIXTURE_DIR / "return_wrong_sku_text.png").read_bytes()

    payload = {
        "sku": "PHONE-OK123",
        "uid": "u-sku-mismatch",
        "images": [{"filename": "wrong_sku.png", "b64": base64.b64encode(wrong_sku_img).decode("ascii")}],
        "description": "return",
    }
    r = client.post("/api/v1/returns/submit", json=payload)
    assert r.status_code == 200
    reasons = r.json().get("score", {}).get("reasons", [])
    assert "ocr_sku_mismatch" in reasons
