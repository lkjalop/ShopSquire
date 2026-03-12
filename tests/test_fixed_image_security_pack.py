import json
import os

import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


app = create_app()
client = TestClient(app, headers=default_headers())


def _artifact_path(name: str) -> str:
    return os.path.join("dump", "test-cv", name)


def _triage_image(path: str) -> dict:
    with open(path, "rb") as f:
        r = client.post(
            "/api/v1/vision/triage",
            files={"image": (os.path.basename(path), f, "image/png")},
        )
    assert r.status_code == 200, r.text
    return r.json()


def test_fixed_pack_macbook_qr_expected_signals():
    p = _artifact_path("macbook-QR.png")
    if not os.path.isfile(p):
        pytest.skip("macbook-QR.png missing in dump/test-cv")
    body = _triage_image(p)
    sig = ((body.get("security") or {}).get("signals") or {})
    expected = {"qr_code_detected", "payment_social_engineering"}
    missing = sorted([k for k in expected if not bool(sig.get(k))])
    assert not missing, {"missing": missing, "signals": sig}


def test_fixed_pack_ms_texti_expected_signals():
    p = _artifact_path("ms-texti.png")
    if not os.path.isfile(p):
        pytest.skip("ms-texti.png missing in dump/test-cv")
    body = _triage_image(p)
    sig = ((body.get("security") or {}).get("signals") or {})
    expected = {"payment_social_engineering", "pci_card_exposed"}
    missing = sorted([k for k in expected if not bool(sig.get(k))])
    assert not missing, {"missing": missing, "signals": sig, "text": (body.get("extracted_text") or "")[:220]}


def test_fixed_pack_recommend_route_consistency_for_ms_texti():
    p = _artifact_path("ms-texti.png")
    if not os.path.isfile(p):
        pytest.skip("ms-texti.png missing in dump/test-cv")
    triage = _triage_image(p)
    sig = ((triage.get("security") or {}).get("signals") or {})
    params = {
        "uid": "u-fixed-pack-msi",
        "query": "high school university laptop budget 1100",
        "budget_min": 700,
        "budget_max": 1100,
        "k": 6,
        "image_labels": ", ".join(triage.get("labels") or []),
        "image_ocr_text": triage.get("extracted_text") or "",
        "image_hash": triage.get("image_hash") or "",
        "image_cv_signals": json.dumps(sig),
    }
    r = client.get("/api/v1/recommend/suggest", params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body.get("status") in {"review_required", "ok", None}) and (len(body.get("results") or []) >= 1), body
    sec = body.get("security") if isinstance(body.get("security"), dict) else {}
    assert str(sec.get("policy_route") or "") == "visual_sanitized", sec
    assert bool(sec.get("image_untrusted")) is True, sec
    channels = sec.get("image_trust_channels") if isinstance(sec.get("image_trust_channels"), dict) else {}
    assert channels.get("visual_embedding_trusted") is True
    assert channels.get("ocr_trusted") is False
    assert channels.get("qr_trusted") is False
    reasons = body.get("image_reupload_reasons") or []
    assert any(x in reasons for x in ("payment_social_engineering", "pci_card_exposed")), reasons

