from __future__ import annotations

import os
import time
from typing import Any, Dict, List

import httpx


OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
TEXT_MODELS = [
    "vanta-research/apollo-astralis-4b:latest",
    "phi3:mini",
    "llama3.2:3b",
    "llama3.1:8b",
    "llama3:8b",
]
EMBED_MODELS = [
    "nomic-embed-text",
    "mxbai-embed-large",
]
VISION_MODELS = [
    "llava",
    "minicpm-v",
]

# 1x1 PNG
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQI12P4"
    "//8/AwAI/AL+J6sE9QAAAABJRU5ErkJggg=="
)


def _post(path: str, payload: Dict[str, Any], timeout: float = 90.0) -> Dict[str, Any]:
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{OLLAMA_URL}{path}", json=payload)
        r.raise_for_status()
        return r.json()


def _list_models() -> List[str]:
    try:
        data = _post("/api/tags", {}, timeout=10.0)
        return [m.get("name") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def test_text_models() -> List[Dict[str, Any]]:
    results = []
    for model in TEXT_MODELS:
        payload = {
            "model": model,
            "prompt": "Extract intent and slots: 'list laptops between $1500 and $2200 with 32GB RAM'.",
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 96},
        }
        t0 = time.time()
        try:
            data = _post("/api/generate", payload, timeout=120.0)
            results.append(
                {
                    "model": model,
                    "ok": True,
                    "latency_s": round(time.time() - t0, 2),
                    "response": (data.get("response") or "").strip(),
                }
            )
        except Exception as exc:
            results.append({"model": model, "ok": False, "error": str(exc)})
    return results


def test_embed_models() -> List[Dict[str, Any]]:
    results = []
    for model in EMBED_MODELS:
        payload = {"model": model, "prompt": "gaming laptop under $2000 with RTX"}
        t0 = time.time()
        try:
            data = _post("/api/embeddings", payload, timeout=60.0)
            emb = data.get("embedding") or []
            results.append(
                {
                    "model": model,
                    "ok": True,
                    "latency_s": round(time.time() - t0, 2),
                    "dim": len(emb),
                }
            )
        except Exception as exc:
            results.append({"model": model, "ok": False, "error": str(exc)})
    return results


def test_vision_models() -> List[Dict[str, Any]]:
    results = []
    for model in VISION_MODELS:
        payload = {
            "model": model,
            "prompt": "Describe the image briefly.",
            "images": [TINY_PNG_B64],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 64},
        }
        t0 = time.time()
        try:
            data = _post("/api/generate", payload, timeout=120.0)
            results.append(
                {
                    "model": model,
                    "ok": True,
                    "latency_s": round(time.time() - t0, 2),
                    "response": (data.get("response") or "").strip(),
                }
            )
        except Exception as exc:
            results.append({"model": model, "ok": False, "error": str(exc)})
    return results


def main() -> None:
    available = _list_models()
    print("OLLAMA_URL:", OLLAMA_URL)
    print("Available models:", ", ".join(available) if available else "unknown")
    print("\n== Text models ==")
    for item in test_text_models():
        print(item)
    print("\n== Embed models ==")
    for item in test_embed_models():
        print(item)
    print("\n== Vision models ==")
    for item in test_vision_models():
        print(item)


if __name__ == "__main__":
    main()
