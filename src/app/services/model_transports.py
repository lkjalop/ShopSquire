"""Transport adapters usable only behind ModelExecutionGateway."""
from __future__ import annotations

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


__all__ = ["ollama_generate_transport"]
