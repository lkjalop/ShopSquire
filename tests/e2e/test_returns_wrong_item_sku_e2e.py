import base64
import os
from pathlib import Path

import pytest
import requests


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "images"


@pytest.mark.integration
def test_returns_wrong_item_sku_mismatch_e2e():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("Integration tests disabled. Set RUN_INTEGRATION=1 to enable.")

    base = os.getenv("INTEGRATION_BASE_URL")
    if not base:
        host = os.getenv("API_HOST", "localhost")
        port = os.getenv("API_PORT", "8080")
        base = f"http://{host}:{port}"

    headers = {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}
    img = (FIXTURE_DIR / "return_wrong_sku_text.png").read_bytes()

    payload = {
        "sku": "PHONE-OK123",
        "uid": "e2e-sku-mismatch-1",
        "images": [{"filename": "wrong_sku.png", "b64": base64.b64encode(img).decode("ascii")}],
        "description": "return",
    }
    r = requests.post(f"{base}/api/v1/returns/submit", json=payload, headers=headers, timeout=10)
    assert r.status_code == 200
    reasons = (r.json().get("score") or {}).get("reasons") or []
    if "no_ocr" in reasons:
        pytest.skip("OCR not available in integration server")
    assert "ocr_sku_mismatch" in reasons
