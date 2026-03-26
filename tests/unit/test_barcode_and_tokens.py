import os
import uuid
import json

import pytest

from src.app.rules import barcode_decode
from src.app.routers import escalation_room
from src.app.deps import DummyRedis


def test_decode_uses_opencv_when_pyzbar_fails(monkeypatch):
    # Simulate pyzbar failing / returning no results, and OpenCV decoding succeeds.
    monkeypatch.setattr(barcode_decode, "_try_decode_pyzbar", lambda b: [])
    monkeypatch.setattr(barcode_decode, "_try_decode_opencv", lambda b: [{"type": "QR_CODE", "data": "hello-world"}])

    res = barcode_decode.decode_barcodes([("img1.jpg", b"fake-bytes")])
    assert res.ok is True
    assert any(c.get("data") == "hello-world" for c in res.codes)
    # Ensure reasons indicate pyzbar had no result and OpenCV decoded
    assert "pyzbar_no_result" in res.reasons
    assert "opencv_decoded" in res.reasons


def test_decode_classifies_benign_qr_payload(monkeypatch):
    monkeypatch.setattr(barcode_decode, "_normalize_image_bytes", lambda b: (b, ["avif_normalized"]))
    monkeypatch.setattr(
        barcode_decode,
        "_try_decode_pyzbar",
        lambda b: [{"type": "QR_CODE", "data": "mailto:support@example.com"}],
    )
    monkeypatch.setattr(barcode_decode, "_try_decode_opencv", lambda b: [])

    res = barcode_decode.decode_barcodes([("img1.avif", b"fake-bytes")])
    assert res.ok is True
    assert "avif_normalized" in res.reasons
    code = res.codes[0]
    assert code["payload_type"] == "email_uri"
    assert code["risk_level"] == "benign"
    assert code["is_benign_qr"] is True


def test_file_backed_tokens_written_and_role_resolves(monkeypatch, tmp_path):
    # Force file-backed tokens by ensuring get_redis returns DummyRedis
    # Reset lazy redis and monkeypatch to DummyRedis instance
    monkeypatch.setattr("src.app.deps._lazy_redis", None)
    monkeypatch.setattr("src.app.deps._redis_warned", True)
    monkeypatch.setattr("src.app.deps._create_redis_client", lambda: None)

    # Use a temporary tokens dir to avoid affecting workspace
    monkeypatch.setattr(escalation_room, "_TOKENS_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    incident_id = f"test-{uuid.uuid4().hex}"
    toks = escalation_room._issue_tokens(incident_id)
    assert toks.get("buyer_token")
    assert toks.get("staff_token")

    # File should exist with persisted tokens
    p = tmp_path / f"{incident_id}.json"
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data.get("buyer") == toks.get("buyer_token")
    assert data.get("staff") == toks.get("staff_token")

    # Role resolution should recognize buyer and staff tokens
    role_buyer = escalation_room._role_for_token(incident_id, toks.get("buyer_token"))
    role_staff = escalation_room._role_for_token(incident_id, toks.get("staff_token"))
    assert role_buyer == "buyer"
    # staff resolves to ROLE_MERCHANT alias in code
    assert role_staff == escalation_room.ROLE_MERCHANT
