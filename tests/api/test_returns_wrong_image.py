import base64
import os
from pathlib import Path

from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images"


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def test_returns_wrong_image_flags_ocr_mismatch(monkeypatch, tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/returns.sqlite"
    app = create_app()
    client = TestClient(app, headers=default_headers())

    ok_img = (FIXTURE_DIR / "return_ok_laptop.png").read_bytes()
    wrong_img = (FIXTURE_DIR / "return_wrong_phone.png").read_bytes()

    # Deterministic OCR for fixtures (uses actual bytes to map).
    import src.app.services.returns as returns_mod

    def _fake_ocr(b: bytes) -> str:
        if b == wrong_img:
            return "PHONE"
        if b == ok_img:
            return "LAPTOP"
        return ""

    monkeypatch.setattr(returns_mod, "ocr_image_bytes", _fake_ocr, raising=True)

    payload_wrong = {
        "sku": "LAPTOP-OK",
        "uid": "u-1",
        "images": [{"filename": "wrong.png", "b64": base64.b64encode(wrong_img).decode("ascii")}],
        "description": "return",
    }
    r1 = client.post("/api/v1/returns/submit", json=payload_wrong)
    assert r1.status_code == 200
    reasons = r1.json().get("score", {}).get("reasons", [])
    assert "ocr_category_mismatch" in reasons

    payload_ok = {
        "sku": "LAPTOP-OK",
        "uid": "u-2",
        "images": [{"filename": "ok.png", "b64": base64.b64encode(ok_img).decode("ascii")}],
        "description": "return",
    }
    r2 = client.post("/api/v1/returns/submit", json=payload_ok)
    assert r2.status_code == 200
    reasons_ok = r2.json().get("score", {}).get("reasons", [])
    assert "ocr_category_mismatch" not in reasons_ok
