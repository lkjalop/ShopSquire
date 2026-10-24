"""Bounded Ollama execution for the recommendation turn router."""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Callable


class RouterOutputTruncated(RuntimeError):
    failure_code = "router_output_truncated"

    def __init__(self, execution_details: dict[str, Any]):
        super().__init__(self.failure_code)
        self.execution_details = dict(execution_details)


def execute_router_model(
    prompt: str,
    timeout: float,
    *,
    model: str,
    http_post: Callable[..., Any],
    injected_transport: bool,
    gate: Any,
    runtime_contract: dict[str, Any],
    prompt_id: str = "recommend-router-v2",
    role: str = "recommendation_turn_router",
) -> tuple[str, dict[str, Any]]:
    execution_id = f"router-run-{uuid.uuid4().hex}"
    started = time.monotonic()
    metrics: dict[str, Any] = {
        "execution_id": execution_id, "provider": "ollama", "model": model,
        "model_version": os.getenv("ROUTER_MODEL_VERSION") or model,
        "prompt_version": prompt_id, "policy_version": "semantic-authority-v1",
        "outcome": "error", "queue_ms": 0.0, "wall_ms": 0.0,
    }
    provider_metrics: dict[str, Any] = {}
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
        acquired = gate.acquire(timeout=min(float(runtime_contract["queue_timeout_s"]), max(0.0, float(timeout))))
        metrics["queue_ms"] = round((time.monotonic() - queued_at) * 1_000.0, 1)
        if not acquired:
            metrics["failure_code"] = "router_queue_timeout"
            metrics["outcome"] = "queue_timeout"
            return "", metrics
        try:
            max_tokens = int(os.getenv("ROUTER_NUM_PREDICT", "768") or 768)
        except (TypeError, ValueError):
            max_tokens = 768
        remaining = float(timeout) - (time.monotonic() - started)
        if remaining < .05:
            from src.app.services.local_model_roles import LocalModelFailure
            raise LocalModelFailure("local_model_deadline_exhausted")
        from src.app.services.local_model_roles import configured_digest, execute_local_model_role

        digest = configured_digest("ROUTER_MODEL_DIGEST", "OLLAMA_DEFAULT_MODEL_DIGEST")
        if injected_transport:
            digest = "0" * 64
        metrics["model_artifact_digest"] = digest
        metrics["artifact_verification_requested"] = bool(digest)

        def transport(model_prompt, deployment, request):
            from src.app.services.recommendation_core.envelope import LANES

            # Constrain the model to the existing contract instead of accepting
            # invented lanes or maintaining a growing alias-repair table.
            output_format: Any = "json"
            if prompt_id == "recommend-router-v2":
                output_format = {
                    "type": "object",
                    "properties": {"lane": {"type": "string", "enum": list(LANES)}},
                    "required": ["lane"],
                    "additionalProperties": True,
                }
            payload: dict[str, Any] = {
                "model": model, "prompt": model_prompt, "stream": False, "format": output_format,
                "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                "options": {"temperature": 0, "num_predict": request.max_output_tokens,
                            "num_ctx": int(os.getenv("OLLAMA_CONTEXT_LENGTH", "4096"))},
            }
            if "qwen3" in model.lower():
                payload["think"] = False
            response = http_post(
                deployment.endpoint, json=payload, timeout=request.timeout_ms / 1_000.0,
            )
            from src.app.services.local_model_roles import LocalModelFailure

            if response.status_code != 200:
                raise LocalModelFailure("router_model_http_error")
            data = response.json() or {}
            provider_metrics.update({
                "http_status": int(response.status_code),
                "provider_total_ms": round(float(data.get("total_duration") or 0) / 1_000_000, 1),
                "load_ms": round(float(data.get("load_duration") or 0) / 1_000_000, 1),
                "prompt_eval_ms": round(float(data.get("prompt_eval_duration") or 0) / 1_000_000, 1),
                "decode_ms": round(float(data.get("eval_duration") or 0) / 1_000_000, 1),
                "prompt_tokens": int(data.get("prompt_eval_count") or 0),
                "output_tokens": int(data.get("eval_count") or 0),
                "done_reason": str(data.get("done_reason") or "unknown"),
            })
            if response.status_code != 200 or data.get("error"):
                raise LocalModelFailure("router_model_http_error")
            if data.get("done_reason") == "length":
                raise RouterOutputTruncated({
                    key: provider_metrics.get(key) for key in (
                        "done_reason", "prompt_tokens", "output_tokens",
                        "provider_total_ms", "prompt_eval_ms", "decode_ms",
                    )
                })
            from src.app.services.model_transports import ModelTransportText

            return ModelTransportText(
                str(data.get("response") or ""),
                {key: provider_metrics.get(key) for key in (
                    "done_reason", "prompt_tokens", "output_tokens",
                    "provider_total_ms", "prompt_eval_ms", "decode_ms",
                )},
            )

        rendered = execute_local_model_role(
            prompt, role=role, purpose="route_buyer_recommendation_turn",
            prompt_id=prompt_id, model=model, digest=digest, timeout_s=remaining,
            max_output_tokens=max_tokens, transport=transport, execution_id=execution_id,
        )
        metrics["outcome"] = "ok"
        return rendered, metrics
    except Exception as exc:
        if provider_metrics.get("done_reason") == "length" or isinstance(exc, RouterOutputTruncated) or getattr(exc, "failure_code", None) == "router_output_truncated":
            metrics["outcome"] = "truncated"
            metrics["failure_code"] = "router_output_truncated"
        else:
            code = getattr(exc, "failure_code", None)
            timed_out = "timeout" in str(code or type(exc).__name__).lower() or code == "local_model_deadline_exhausted"
            metrics["outcome"] = "timeout" if timed_out else "error"
            metrics["failure_code"] = (
                code or ("model_execution_timeout" if timed_out else "model_execution_failed")
            )
        metrics["error_type"] = type(exc).__name__
        return "", metrics
    finally:
        metrics.update(dict(provider_metrics))
        if acquired:
            gate.release()
        try:
            from src.app.services.local_model_roles import last_local_model_schedule_metrics

            schedule = last_local_model_schedule_metrics()
            if schedule.get("execution_id") == execution_id:
                metrics.update({
                    "verification_ms": schedule.get("verification_ms"),
                    "scheduler_role": schedule.get("role"),
                    "scheduler_priority": schedule.get("priority"),
                    "scheduler_status": schedule.get("status"),
                    "scheduler_failure_code": schedule.get("failure_code"),
                    "scheduler_queue_ms": schedule.get("queue_ms"),
                    "scheduler_execution_ms": schedule.get("execution_ms"),
                    "scheduler_deadline_ms": schedule.get("deadline_ms"),
                    "scheduler_cancelled": schedule.get("cancelled"),
                })
        except Exception:
            pass
        metrics["wall_ms"] = round((time.monotonic() - started) * 1_000.0, 1)
        metrics["model_execution_ms"] = round(sum(float(metrics.get(key) or 0) for key in (
            "load_ms", "prompt_eval_ms", "decode_ms",
        )), 1)
        metrics["provider_timing_available"] = "provider_total_ms" in metrics
        metrics["execution_wait_ms"] = float(metrics.get("scheduler_execution_ms") or 0)
        if not metrics["provider_timing_available"]:
            metrics["model_execution_ms"] = metrics["execution_wait_ms"]
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
