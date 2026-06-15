"""P0 regression: the deterministic QR/steg security detectors must NOT be
cancelled when the slow vision-LLM (tier2) task times out.

Before the fix, /cv/analyze ran tier2 + consistency + QR in one
wait_for(gather(...)); a tier2/Ollama hang cancelled the <100ms QR decode too,
silently failing OPEN on QR/SSN-exfil. This proves QR survives a tier2 timeout.
"""
from __future__ import annotations

import base64
import os
import time

import pytest

IMG = "dump/test-cv/msi-SSN.png"  # contains a real QR (https://scanned.page/p/...)


def _find(obj, key):
    out = []
    def rec(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == key:
                    out.append(v)
                rec(v)
        elif isinstance(o, list):
            for x in o:
                rec(x)
    rec(obj)
    return out


@pytest.mark.skipif(not os.path.exists(IMG), reason="test image not present")
def test_qr_survives_vision_llm_timeout(monkeypatch):
    monkeypatch.setenv("CV_STRICT_RUNTIME_DEPS", "0")
    monkeypatch.setenv("CV_ANALYZE_TIMEOUT_SEC", "2")   # tier2/consistency budget
    monkeypatch.setenv("CV_QR_TIMEOUT_SEC", "8")        # QR budget must outlast tier2

    import src.app.routers.cv as cvmod
    # Make the heavy vision task hang well past its budget (simulates Ollama/model stall).
    monkeypatch.setattr(cvmod, "run_tier2", lambda *a, **k: (time.sleep(10), {})[1])

    from fastapi.testclient import TestClient
    from src.app.main import create_app

    client = TestClient(create_app())
    b64 = base64.b64encode(open(IMG, "rb").read()).decode()
    r = client.post(
        "/api/v1/cv/analyze",
        headers={"x-api-key": "local-owner-key"},
        json={"case_id": "qr-decouple", "images_b64": [b64]},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    qr_flags = _find(body, "qr_code_detected")
    assert any(bool(v) for v in qr_flags), (
        f"QR not surfaced despite a real QR present — fail-open regression. "
        f"qr_code_detected={qr_flags}, top-level keys={list(body)[:20]}"
    )
