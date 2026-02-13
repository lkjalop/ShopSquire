from __future__ import annotations

import os
import time
from typing import Dict
from src.app.services.decision_log import log_trace_event

import httpx

SMALL_DEFAULT = os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b")
BIG_DEFAULT = os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")


def is_complex_query(query: str) -> bool:
    q = (query or "").lower().strip()
    if len(q) > 140:
        return True
    keywords = [
        "compare",
        "tradeoff",
        "explain",
        "justify",
        "policy",
        "compliance",
        "virtualization",
        "cad",
        "passthrough",
        "architecture",
        "train",
        "training",
        "fine-tune",
        "finetune",
        "llm",
        "gpu",
        "vram",
        "cuda",
    ]
    if any(k in q for k in keywords):
        return True
    # Count conjunctions and clauses as a weak proxy
    conj = sum(q.count(k) for k in [" and ", " or ", ", "])
    return conj >= 2


def select_ollama_model(query: str) -> str:
    return BIG_DEFAULT if is_complex_query(query) else SMALL_DEFAULT


def complexity_explain(query: str) -> Dict:
    """Return a structured explanation of complexity classification.

    Includes signals: length_trigger, matched_keywords, conjunction_count, and a simple score.
    """
    q = (query or "").lower().strip()
    length_trigger = len(q) > 140
    keywords = [
        "compare",
        "tradeoff",
        "explain",
        "justify",
        "policy",
        "compliance",
        "virtualization",
        "cad",
        "passthrough",
        "architecture",
        "train",
        "training",
        "fine-tune",
        "finetune",
        "llm",
        "gpu",
        "vram",
        "cuda",
    ]
    matched = [k for k in keywords if k in q]
    conj = sum(q.count(k) for k in [" and ", " or ", ", "])
    score = (3 if length_trigger else 0) + len(matched) + (1 if conj >= 2 else 0)
    return {
        "length_trigger": length_trigger,
        "matched_keywords": matched,
        "conjunction_count": conj,
        "score": score,
    }


async def ollama_generate(model: str, prompt: str, options: Dict | None = None, trace_id: str | None = None) -> Dict:
    if not OLLAMA_URL:
        err = RuntimeError("OLLAMA_URL_missing")
        # surface via trace if available
        try:
            log_trace_event(trace_id, "llm_error", "llm", model, "system", None, {"error": str(err)})
        except Exception:
            pass
        raise err
    payload: Dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 256,
        },
    }
    if options:
        payload["options"].update(options)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{OLLAMA_URL.rstrip('/')}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
        dt = (time.perf_counter() - t0) * 1000.0
        return {
            "model": model,
            "response": data.get("response"),
            "total_duration_ms": dt,
        }
    except Exception as e:
        # best-effort: log trace event so UI/telemetry surface LLM failures
        try:
            log_trace_event(trace_id, "llm_error", "llm", model, "system", None, {"error": str(e), "payload": {"prompt_len": len(prompt) if prompt else 0}})
        except Exception:
            pass
        raise
