"""Bounded Ollama execution for the recommendation turn router."""
from __future__ import annotations

import os
import time
from typing import Any, Callable


def execute_router_model(
    prompt: str,
    timeout: float,
    *,
    model: str,
    http_post: Callable[..., Any],
    injected_transport: bool,
    gate: Any,
    runtime_contract: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    started = time.monotonic()
    metrics: dict[str, Any] = {
        "provider": "ollama", "model": model,
        "model_version": os.getenv("ROUTER_MODEL_VERSION") or model,
        "prompt_version": "recommend-router-v2", "policy_version": "semantic-authority-v1",
        "outcome": "error", "queue_ms": 0.0, "wall_ms": 0.0,
    }
    acquired = False
    try:
        explicitly_enabled = str(os.getenv("ROUTER_MODEL_ENABLED", "")).strip().lower()
        mock_runtime = str(os.getenv("USE_MOCK_LLM", "")).strip().lower() in {
            "1", "true", "yes", "on",
        }
        enabled = (
            explicitly_enabled in {"1", "true", "yes", "on"}
            if explicitly_enabled else not mock_runtime
        )
        if not enabled:
            metrics["provider"] = "mock" if mock_runtime else "disabled"
            metrics["outcome"] = "mock_disabled" if mock_runtime else "disabled"
            return "", metrics
        queued_at = time.monotonic()
        acquired = gate.acquire(timeout=float(runtime_contract["queue_timeout_s"]))
        metrics["queue_ms"] = round((time.monotonic() - queued_at) * 1_000.0, 1)
        if not acquired:
            metrics["outcome"] = "queue_timeout"
            return "", metrics
        try:
            max_tokens = int(os.getenv("ROUTER_NUM_PREDICT", "320") or 320)
        except (TypeError, ValueError):
            max_tokens = 320
        remaining = max(2.0, float(timeout or 20.0) - metrics["queue_ms"] / 1_000.0)
        from src.app.services.local_model_roles import configured_digest, execute_local_model_role

        digest = configured_digest("ROUTER_MODEL_DIGEST", "OLLAMA_DEFAULT_MODEL_DIGEST")
        if injected_transport:
            digest = "0" * 64

        def transport(model_prompt, deployment, request):
            payload: dict[str, Any] = {
                "model": model, "prompt": model_prompt, "stream": False, "format": "json",
                "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                "options": {"temperature": 0, "num_predict": request.max_output_tokens},
            }
            if "qwen3" in model.lower():
                payload["think"] = False
            response = http_post(
                deployment.endpoint, json=payload, timeout=request.timeout_ms / 1_000.0,
            )
            data = response.json() or {}
            metrics.update({
                "http_status": int(response.status_code),
                "provider_total_ms": round(float(data.get("total_duration") or 0) / 1_000_000, 1),
                "load_ms": round(float(data.get("load_duration") or 0) / 1_000_000, 1),
                "prompt_eval_ms": round(float(data.get("prompt_eval_duration") or 0) / 1_000_000, 1),
                "decode_ms": round(float(data.get("eval_duration") or 0) / 1_000_000, 1),
                "prompt_tokens": int(data.get("prompt_eval_count") or 0),
                "output_tokens": int(data.get("eval_count") or 0),
            })
            if response.status_code != 200 or data.get("error"):
                raise RuntimeError("router_model_http_error")
            return str(data.get("response") or "")

        rendered = execute_local_model_role(
            prompt, role="recommendation_turn_router", purpose="route_buyer_recommendation_turn",
            prompt_id="recommend-router-v2", model=model, digest=digest, timeout_s=remaining,
            max_output_tokens=max_tokens, transport=transport,
        )
        metrics["outcome"] = "ok"
        return rendered, metrics
    except Exception as exc:
        metrics["outcome"] = "timeout" if "timeout" in type(exc).__name__.lower() else "error"
        metrics["error_type"] = type(exc).__name__
        return "", metrics
    finally:
        if acquired:
            gate.release()
        metrics["wall_ms"] = round((time.monotonic() - started) * 1_000.0, 1)
        metrics["model_execution_ms"] = round(sum(float(metrics.get(key) or 0) for key in (
            "load_ms", "prompt_eval_ms", "decode_ms",
        )), 1)
        provider_ms = float(metrics.get("provider_total_ms") or 0)
        metrics["provider_internal_overhead_ms"] = round(max(
            0.0, provider_ms - float(metrics["model_execution_ms"]),
        ), 1)
        metrics["transport_overhead_ms"] = round(max(
            0.0, float(metrics["wall_ms"]) - float(metrics.get("queue_ms") or 0) - provider_ms,
        ), 1) if provider_ms else 0.0
        metrics["provider_overhead_ms"] = round(
            float(metrics["provider_internal_overhead_ms"])
            + float(metrics["transport_overhead_ms"]), 1,
        )


__all__ = ["execute_router_model"]
