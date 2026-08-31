"""Transport adapters usable only behind ModelExecutionGateway."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import requests

from src.app.services.model_execution_gateway import ModelDeployment, ModelExecutionRequest


def ollama_generate_transport(
    prompt: str, deployment: ModelDeployment, request: ModelExecutionRequest,
) -> str:
    response = requests.post(
        deployment.endpoint,
        json={
            "model": deployment.model_artifact_id.split("@", 1)[0],
            "prompt": prompt,
            "stream": False,
            "think": False,
            "keep_alive": "10m",
            "options": {
                "temperature": 0,
                "num_predict": request.max_output_tokens,
            },
        },
        timeout=request.timeout_ms / 1_000.0,
    )
    response.raise_for_status()
    return str(response.json().get("response") or "")


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
            "options": {**frozen_options, "num_predict": request.max_output_tokens},
        }
        if response_format is not None:
            payload["format"] = response_format
        if frozen_images:
            payload["images"] = list(frozen_images)
        response = requests.post(
            deployment.endpoint,
            json=payload,
            timeout=request.timeout_ms / 1_000.0,
        )
        response.raise_for_status()
        return str(response.json().get("response") or "")

    return transport


__all__ = ["make_ollama_generate_transport", "ollama_generate_transport"]
