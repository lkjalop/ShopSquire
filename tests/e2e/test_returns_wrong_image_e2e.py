import base64
import os
import pytest
import requests
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images"


@pytest.mark.integration
def test_returns_wrong_image_e2e():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("Integration tests disabled. Set RUN_INTEGRATION=1 to enable.")

    base = os.getenv("INTEGRATION_BASE_URL")
    if not base:
        host = os.getenv("API_HOST", "localhost")
        port = os.getenv("API_PORT", "8080")
        base = f"http://{host}:{port}"

    headers = {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}
    wrong_img = (FIXTURE_DIR / "return_wrong_phone.png").read_bytes()

    payload = {
        "sku": "LAPTOP-OK",
        "uid": "e2e-returns-1",
        "images": [{"filename": "wrong.png", "b64": base64.b64encode(wrong_img).decode("ascii")}],
        "description": "return",
    }
    r = requests.post(f"{base}/api/v1/returns/submit", json=payload, headers=headers, timeout=10)
    assert r.status_code == 200
    score = r.json().get("score", {})
    reasons = score.get("reasons", [])

    # Some integration servers may not have OCR deps; tolerate that by skipping.
    if "no_ocr" in reasons:
        pytest.skip("OCR not available in integration server")
    assert ("ocr_category_mismatch" in reasons) or ("ocr_sku_mismatch" in reasons)
