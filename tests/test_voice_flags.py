import base64

from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers

app = create_app()
client = TestClient(app, headers=default_headers())


def test_voice_asr_disabled():
    r = client.post("/api/v1/voice/asr", json={"audio_b64": "AAA=", "format": "webm"})
    assert r.status_code == 503


def test_voice_tts_disabled():
    r = client.post("/api/v1/voice/tts", json={"text": "hello"})
    assert r.status_code == 503


def test_voice_asr_accepts_typed_json_and_reports_provenance(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "src.app.routers.voice._ff_get_flags",
        lambda: {"CAPABILITIES": {"voice": {"asr": True, "tts": True}}},
    )
    def fake_transcribe(_self, audio, lang_hint=None, format_hint="webm"):
        captured.update({
            "audio": audio,
            "language": lang_hint,
            "format": format_hint,
        })
        return {
            "text": "twenty work laptops",
            "confidence": 0.91,
            "provider": "test-asr",
            "status": "ready",
        }

    monkeypatch.setattr(
        "src.app.routers.voice.WhisperLocalASRAdapter.transcribe_chunk",
        fake_transcribe,
    )
    audio = base64.b64encode(b"valid voice bytes" * 4).decode("ascii")
    response = client.post(
        "/api/v1/voice/asr",
        json={"audio_b64": audio, "format": "webm", "language": "en-AU"},
        headers={**default_headers(), "X-Tenant-Id": "tenant-a"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "twenty work laptops"
    assert body["provider"] == "test-asr"
    assert body["status"] == "ready"
    assert body["latency_ms"] >= 0
    assert captured["language"] == "en-AU"
    assert captured["format"] == "webm"


def test_voice_asr_rejects_invalid_or_oversized_audio(monkeypatch):
    monkeypatch.setattr(
        "src.app.routers.voice._ff_get_flags",
        lambda: {"CAPABILITIES": {"voice": {"asr": True, "tts": True}}},
    )
    invalid = client.post(
        "/api/v1/voice/asr",
        json={"audio_b64": "not-base64!", "format": "webm"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "invalid_audio"

    monkeypatch.setenv("VOICE_MAX_AUDIO_BYTES", "32")
    oversized = client.post(
        "/api/v1/voice/asr",
        json={
            "audio_b64": base64.b64encode(b"x" * 64).decode("ascii"),
            "format": "webm",
        },
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"] == "audio_too_large"


def test_voice_tts_reports_unavailable_instead_of_fake_audio(monkeypatch):
    monkeypatch.setattr(
        "src.app.routers.voice._ff_get_flags",
        lambda: {"CAPABILITIES": {"voice": {"asr": True, "tts": True}}},
    )
    monkeypatch.setattr(
        "src.app.routers.voice.ElevenLabsTTSAdapter.synthesize",
        lambda _self, text, voice=None: {
            "audio_base64": "",
            "confidence": 0.0,
            "provider": "none",
            "mime_type": None,
            "status": "unavailable",
        },
    )
    response = client.post("/api/v1/voice/tts", json={"text": "Response ready."})
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"
    assert response.json()["audio_base64"] == ""


def test_legacy_voice_websocket_is_disabled_for_pilot(monkeypatch):
    monkeypatch.setattr(
        "src.app.routers.voice._ff_get_flags",
        lambda: {"CAPABILITIES": {"voice": {"asr": True, "tts": True}}},
    )
    with client.websocket_connect("/api/v1/voice/stream") as websocket:
        message = websocket.receive_json()
        assert message == {
            "type": "error",
            "detail": "legacy_voice_stream_disabled_use_chat_stream",
        }
