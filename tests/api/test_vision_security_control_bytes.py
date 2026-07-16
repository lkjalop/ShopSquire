"""P0-2 (test-anchored roadmap 2026-07-16): the QR/barcode decoder and the adversarial detector are
SECURITY controls — they must run on the FULL-RES upload, not the downscaled VLM copy.

The size-gate (commit e9ede2e) correctly routes the VLM/OCR to a ~1280px downscale and keeps steg +
phash on raw bytes. But the batch also routed QR decode + adversarial detection through the
downscaled bytes. QR feeds the `qr_external_url_detected -> text_only` wipe, so a small malicious QR
in a large image could decode at full-res yet be lost at 1280px -> a FAIL-OPEN erosion of a security
signal. This test pins that QR + adversarial see full-res.

DONE = both controls receive the full-res dimensions (2000x2000), not the 1280px downscale.
"""
from __future__ import annotations

import io

from fastapi.testclient import TestClient

from src.app.main import create_app


def _big_png(w=2000, h=2000) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (123, 90, 60)).save(buf, format="PNG")
    return buf.getvalue()


def _dims(blob: bytes):
    from PIL import Image
    with Image.open(io.BytesIO(blob)) as im:
        return im.size


def test_qr_and_adversarial_run_on_full_res_not_downscaled(monkeypatch):
    import src.app.routers.vision as vision
    import src.app.rules.barcode_decode as barcode_decode
    import src.app.security.adversarial_image_detector as adv

    async def _fake_labels(self, _blob, mode="visual_search"):
        return [], "", None

    def _fake_analyze(self, _labels, _text, **_kw):
        return {"damage_type": "unknown", "severity": "undetermined", "confidence": 0.2}

    monkeypatch.setattr(vision.ManagedCVProvider, "get_labels_and_text", _fake_labels)
    monkeypatch.setattr(vision.BasicCVTriage, "analyze", _fake_analyze)

    captured = {}

    def _cap_decode(items):
        if items:
            captured["qr_dims"] = _dims(items[0][1])
        return []

    def _cap_adv(blob):
        captured["adv_dims"] = _dims(blob)
        return {}  # no is_adversarial/diffusion_score attrs -> signal logic skipped

    monkeypatch.setattr(barcode_decode, "decode_barcodes", _cap_decode)
    monkeypatch.setattr(adv, "detect_adversarial", _cap_adv)

    client = TestClient(create_app())
    r = client.post("/api/v1/vision/triage",
                    headers={"x-api-key": "local-merchant-key"},
                    files={"image": ("big.png", _big_png(), "image/png")})
    assert r.status_code == 200, r.text

    assert captured.get("qr_dims") == (2000, 2000), (
        f"QR/barcode decode ran on downscaled bytes {captured.get('qr_dims')}, not full-res "
        "(2000, 2000) — a small malicious QR could be lost after downscaling.")
    assert captured.get("adv_dims") == (2000, 2000), (
        f"adversarial detection ran on downscaled bytes {captured.get('adv_dims')}, not full-res "
        "(2000, 2000) — downscaling attenuates adversarial perturbations.")
