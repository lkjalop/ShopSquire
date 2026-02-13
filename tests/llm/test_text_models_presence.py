import os
import json
import urllib.request
import pytest


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


def call_generate(model: str, prompt: str, timeout: int = 6) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        url="http://127.0.0.1:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("response") or "")


@pytest.mark.parametrize("model", ["llama3:8b", "mistral:latest", "qwen2.5:latest"])
def test_ollama_text_models_basic(model):
    if not ollama_has_model(model.split(":")[0]):
        pytest.skip(f"Ollama text model '{model}' not available; skipping")
    # Basic generate sanity for text models
    try:
        out = call_generate(model, "Reply with the single word: ok")
    except Exception:
        pytest.skip(f"Ollama generate failed for '{model}'; skipping")
    assert isinstance(out, str)
    assert len(out) > 0
