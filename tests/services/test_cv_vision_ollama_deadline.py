import time

import requests

from src.app.services.cv_vision_ollama import vision_analyze_with_ollama


def test_disconnect_retries_share_one_total_deadline(monkeypatch):
    calls = []

    def disconnected(_url, **kwargs):
        calls.append(float(kwargs["timeout"]))
        time.sleep(0.06)
        raise requests.exceptions.Timeout("provider disconnected")

    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:65534")
    monkeypatch.setattr("src.app.services.cv_vision_ollama.requests.post", disconnected)
    started = time.monotonic()
    result = vision_analyze_with_ollama(
        b"not-an-image", model="qwen3-vl:8b", timeout_s=0.1,
    )
    elapsed = time.monotonic() - started

    assert result["ok"] is False
    assert result["error"] == "ollama_timeout"
    assert len(calls) == 1
    # Image normalization and URL-policy checks sit outside transport time, but fallback/retry
    # must not multiply the 100 ms provider budget into seconds.
    assert elapsed < 0.5
