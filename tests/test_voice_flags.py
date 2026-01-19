from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)


def test_voice_asr_disabled():
    r = client.post("/api/v1/voice/asr", params={"audio_base64": "AAA"})
    assert r.status_code == 503


def test_voice_tts_disabled():
    r = client.post("/api/v1/voice/tts", params={"text": "hello"})
    assert r.status_code == 503
