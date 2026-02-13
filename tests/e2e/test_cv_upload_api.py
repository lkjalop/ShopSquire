import base64
import json
import pytest
import requests

API_URL = "http://127.0.0.1:8081"

# Small 1x1 PNG base64
SAMPLE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


@pytest.mark.skipif(True, reason="Manual run: requires local server")
def test_cv_upload_flow_api_noninteractive():
    # This is a simple API-level e2e test that fetches a nonce and uploads a capture
    # Run only when local server (uvicorn) is running on port 8081
    resp = requests.get(API_URL + "/api/v1/cv/nonce", timeout=5)
    assert resp.status_code == 200
    j = resp.json()
    nonce = j.get("nonce")
    payload = {"image_b64s": ["data:image/png;base64," + SAMPLE_PNG_B64], "nonce": nonce}
    up = requests.post(API_URL + "/api/v1/cv/upload", json=payload, timeout=10)
    assert up.status_code in (200, 201)
    out = up.json()
    # Expect the endpoint to return either a cv_tier2 block or a verdict wrapper
    assert isinstance(out, dict)
    assert "cv_tier2" in out or "verdict" in out or "cv" in out
