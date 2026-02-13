from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class OllamaResponse:
    text: str
    model: str
    tokens_prompt: int
    tokens_completion: int
    duration_ms: float


class OllamaClient:
    """Minimal client for a local Ollama server.

    This is used for demo purposes; production routing should live in a
    dedicated model router and include guardrails and fallbacks.
    """

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
    ):
        self.base_url = (base_url or os.getenv("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.default_model = default_model or os.getenv("OLLAMA_DEFAULT_MODEL", "llama3.2:3b")

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 512,
        stop: Optional[List[str]] = None,
        system: Optional[str] = None,
    ) -> OllamaResponse:
        payload: Dict[str, Any] = {
            "model": model or self.default_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "stop": stop or [],
            },
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.base_url}/api/generate", json=payload)
            data = resp.json()
        return OllamaResponse(
            text=data.get("response", ""),
            model=payload["model"],
            tokens_prompt=int(data.get("prompt_eval_count", 0) or 0),
            tokens_completion=int(data.get("eval_count", 0) or 0),
            duration_ms=float(data.get("total_duration", 0) or 0) / 1_000_000.0,
        )

    async def embed(self, text: str, model: str = "nomic-embed-text") -> List[float]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": model, "prompt": text},
            )
            data = resp.json()
        return list(data.get("embedding", []) or [])
