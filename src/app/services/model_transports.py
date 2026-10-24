"""Transport adapters usable only behind ModelExecutionGateway."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import os
import requests

from src.app.services.model_execution_gateway import ModelDeployment, ModelExecutionRequest
from src.app.services.ollama_endpoint import normalize_ollama_url


_OLLAMA_SESSION = requests.Session()


def _post_ollama(endpoint: str, **kwargs: Any):
    return _OLLAMA_SESSION.post(normalize_ollama_url(endpoint), **kwargs)


class ModelTransportText(str):
    """String-compatible model output carrying sanitized execution accounting."""

    execution_details: dict[str, Any]

    def __new__(cls, value: str, execution_details: dict[str, Any] | None = None):
        obj = str.__new__(cls, value)
        obj.execution_details = dict(execution_details or {})
        return obj


def _ollama_execution_details(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "done_reason": str(payload.get("done_reason") or "unknown")[:40],
        "prompt_tokens": int(payload.get("prompt_eval_count") or 0),
        "output_tokens": int(payload.get("eval_count") or 0),
        "provider_total_ms": round(float(payload.get("total_duration") or 0) / 1_000_000, 1),
        "prompt_eval_ms": round(float(payload.get("prompt_eval_duration") or 0) / 1_000_000, 1),
        "decode_ms": round(float(payload.get("eval_duration") or 0) / 1_000_000, 1),
    }


def ollama_generate_transport(
    prompt: str, deployment: ModelDeployment, request: ModelExecutionRequest,
) -> str:
    response = _post_ollama(
        deployment.endpoint,
        json={
            "model": deployment.model_artifact_id.split("@", 1)[0],
            "prompt": prompt,
            "stream": False,
            "think": False,
            "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "2m"),
            "options": {
                "temperature": 0,
                "num_predict": request.max_output_tokens,
                "num_ctx": int(os.getenv("OLLAMA_CONTEXT_LENGTH", "4096")),
            },
        },
        timeout=request.timeout_ms / 1_000.0,
    )
    response.raise_for_status()
    payload = response.json() or {}
    return ModelTransportText(
        str(payload.get("response") or ""), _ollama_execution_details(payload)
    )


def make_ollama_generate_transport(
    *,
    images: Sequence[str] = (),
    options: dict[str, Any] | None = None,
    keep_alive: str = "10m",
    think: bool = False,
    response_format: str | dict[str, Any] | None = None,
):
    """Build a payload-specific transport which remains behind the gateway."""

    frozen_images = tuple(str(value) for value in images)
    frozen_options = dict(options or {})

    def transport(
        prompt: str, deployment: ModelDeployment, request: ModelExecutionRequest,
    ) -> str:
        payload: dict[str, Any] = {
            "model": deployment.model_artifact_id.split("@", 1)[0],
            "prompt": prompt,
            "stream": False,
            "think": think,
            "keep_alive": keep_alive,
            "options": {"num_ctx": int(os.getenv("OLLAMA_CONTEXT_LENGTH", "4096")),
                        **frozen_options, "num_predict": request.max_output_tokens},
        }
        if response_format is not None:
            payload["format"] = response_format
        if frozen_images:
            payload["images"] = list(frozen_images)
        response = _post_ollama(
            deployment.endpoint,
            json=payload,
            timeout=request.timeout_ms / 1_000.0,
        )
        response.raise_for_status()
        response_payload = response.json() or {}
        return ModelTransportText(
            str(response_payload.get("response") or ""),
            _ollama_execution_details(response_payload),
        )

    return transport


__all__ = [
    "ModelTransportText", "make_ollama_generate_transport",
    "ollama_generate_transport",
]
