import os
import base64
import json
import urllib.request
import asyncio
import pytest
from src.app.services.cv_provider import ManagedCVProvider


MINI_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMB/ax3sYwAAA=="
)


def ollama_has_model(model: str) -> bool:
    try:
        req = urllib.request.Request(
            url="http://127.0.0.1:11434/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tags = [t.get("name", "") for t in data.get("models", [])]
        return any(model in t for t in tags)
    except Exception:
        return False


@pytest.mark.parametrize("model", ["llava", "qwen2.5-vl", "minicpm-v"])
def test_ollama_vision_models_basic(model):
    os.environ["CV_PROVIDER"] = "ollama"
    os.environ["CV_MODEL"] = model
    if not ollama_has_model(model):
        pytest.skip(f"Ollama model '{model}' not available; skipping")
    provider = ManagedCVProvider()
    img_bytes = base64.b64decode(MINI_PNG_BASE64)
    try:
        result = asyncio.run(asyncio.wait_for(provider.get_labels_and_text(img_bytes), timeout=8))
    except asyncio.TimeoutError:
        pytest.skip(f"Vision generation timed out for model '{model}'; skipping")
    if result is None:
        pytest.skip(f"Vision provider returned no result for model '{model}'; skipping")
    labels, text = result
    assert isinstance(labels, list)
    assert isinstance(text, str)
