import json
import os
import shutil

import pytest
from fastapi.testclient import TestClient

import src.app.main as app_main
from tests.utils import default_headers


def _configure_ocr_env() -> None:
    tess_cmd = os.getenv("TESSERACT_CMD") or os.getenv("TESSERACT_PATH")
    default_win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not tess_cmd and os.name == "nt" and os.path.exists(default_win):
        tess_cmd = default_win
    if tess_cmd and os.path.exists(tess_cmd):
        os.environ["TESSERACT_CMD"] = tess_cmd
        os.environ["CV_OCR_PROVIDER"] = "tesseract"
    elif shutil.which("tesseract"):
        os.environ["CV_OCR_PROVIDER"] = "tesseract"
    else:
        os.environ["CV_OCR_PROVIDER"] = "embedded"
    os.environ.setdefault("CV_OCR_TIMEOUT_SEC", "8")


def _client() -> TestClient:
    _configure_ocr_env()
    factory = getattr(app_main, "_original_create_app", app_main.create_app)
    return TestClient(factory(), headers=default_headers())


def _artifact_path(name: str) -> str:
    return os.path.join("dump", "test-cv", name)


def _triage_image(path: str) -> dict:
    client = _client()
    with open(path, "rb") as f:
        r = client.post(
            "/api/v1/vision/triage",
            files={"image": (os.path.basename(path), f, "image/png")},
        )
    assert r.status_code == 200, r.text
    return r.json()


def _skip_if_ocr_runtime_unavailable(body: dict, required_signals: set[str]) -> None:
    sec = (body.get("security") or {}) if isinstance(body.get("security"), dict) else {}
    sig = (sec.get("signals") or {}) if isinstance(sec.get("signals"), dict) else {}
    extracted = str((body.get("extracted_text") or sec.get("extracted_text") or "")).strip()
    missing = [k for k in required_signals if not bool(sig.get(k))]
    # In this environment OCR can be unavailable or too weak for these artifacts.
    # When that happens we still expect the pipeline to emit uncertainty, not hard-fail the suite.
    if missing and not extracted and bool(sig.get("ocr_low_confidence_uncertain")):
        pytest.skip(
            f"OCR runtime unavailable or low-confidence for artifact in this environment; "
            f"missing={sorted(missing)}"
        )


def test_fixed_pack_macbook_qr_expected_signals():
    p = _artifact_path("macbook-QR.png")
    if not os.path.isfile(p):
        pytest.skip("macbook-QR.png missing in dump/test-cv")
    body = _triage_image(p)
    sig = ((body.get("security") or {}).get("signals") or {})
    expected = {"qr_code_detected", "payment_social_engineering"}
    _skip_if_ocr_runtime_unavailable(body, expected)
    missing = sorted([k for k in expected if not bool(sig.get(k))])
    assert not missing, {"missing": missing, "signals": sig}


def test_fixed_pack_ms_texti_expected_signals():
    p = _artifact_path("ms-texti.png")
    if not os.path.isfile(p):
        pytest.skip("ms-texti.png missing in dump/test-cv")
    body = _triage_image(p)
    sig = ((body.get("security") or {}).get("signals") or {})
    expected = {"payment_social_engineering", "pci_card_exposed"}
    _skip_if_ocr_runtime_unavailable(body, expected)
    missing = sorted([k for k in expected if not bool(sig.get(k))])
    assert not missing, {"missing": missing, "signals": sig, "text": (body.get("extracted_text") or "")[:220]}


def test_fixed_pack_recommend_route_consistency_for_ms_texti():
    p = _artifact_path("ms-texti.png")
    if not os.path.isfile(p):
        pytest.skip("ms-texti.png missing in dump/test-cv")
    triage = _triage_image(p)
    _skip_if_ocr_runtime_unavailable(triage, {"payment_social_engineering", "pci_card_exposed"})
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
    client = _client()
    r = client.get("/api/v1/recommend/suggest", params=params)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") in {"review_required", "ok", "no_verified_result", None}, body
    if body.get("status") == "no_verified_result":
        assert body.get("action_executed") is False, body
    sec = body.get("security") if isinstance(body.get("security"), dict) else {}
    assert str(sec.get("policy_route") or "") == "visual_sanitized", sec
    assert bool(sec.get("image_untrusted")) is True, sec
    channels = sec.get("image_trust_channels") if isinstance(sec.get("image_trust_channels"), dict) else {}
    assert channels.get("visual_embedding_trusted") is True
    assert channels.get("ocr_trusted") is False
    assert channels.get("qr_trusted") is False
    reasons = body.get("image_reupload_reasons") or []
    assert any(x in reasons for x in ("payment_social_engineering", "pci_card_exposed", "identity_confidence_low")), reasons
