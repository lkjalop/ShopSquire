"""Reusable Ollama-only role execution behind ModelExecutionGateway."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from urllib.parse import urlsplit

from src.app.services.agent_run_event_store import application_agent_run_ledger
from src.app.services.model_execution_gateway import (
    ModelDeployment,
    ModelExecutionGateway,
    ModelExecutionRequest,
    Transport,
    sha256_text,
)
from src.app.services.model_transports import ollama_generate_transport
from src.app.services.ollama_artifact_verification import verify_ollama_artifact


_ROLE_PRIORITIES = {
    # Buyer-turn interpretation must not queue behind optional prose.
    "recommendation_turn_router": 0,
    "cart_resolver": 2,
    "recommendation_intent": 4,
    "multi_intent_binder": 4,
    "shopping_plan_extractor": 5,
    "identity_resolver": 10,
    "product_identity": 10,
    "image_ocr": 12,
    "requirement_extractor": 20,
    "catalog_classifier": 22,
    "supplier_document_polisher": 30,
    "market_narrator": 40,
}


@dataclass
class _Waiter:
    priority: int
    sequence: int
    cancelled: bool = False


class _PriorityModelGate:
    """Small process-local priority gate for one Ollama model artifact."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.active = 0
        self.sequence = 0
        self.waiters: list[_Waiter] = []
        self.condition = threading.Condition()

    def acquire(self, *, priority: int, timeout: float) -> tuple[bool, float]:
        started = time.perf_counter()
        with self.condition:
            waiter = _Waiter(priority=priority, sequence=self.sequence)
            self.sequence += 1
            self.waiters.append(waiter)
            self.condition.notify_all()
            deadline = started + max(timeout, 0.0)
            while True:
                live = [item for item in self.waiters if not item.cancelled]
                head = min(live, key=lambda item: (item.priority, item.sequence)) if live else None
                if self.active < self.limit and head is waiter:
                    self.waiters.remove(waiter)
                    self.active += 1
                    return True, (time.perf_counter() - started) * 1_000
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    waiter.cancelled = True
                    if waiter in self.waiters:
                        self.waiters.remove(waiter)
                    self.condition.notify_all()
                    return False, (time.perf_counter() - started) * 1_000
                self.condition.wait(timeout=remaining)

    def release(self) -> None:
        with self.condition:
            self.active = max(0, self.active - 1)
            self.condition.notify_all()


_MODEL_GATES: dict[str, _PriorityModelGate] = {}
_MODEL_GATES_LOCK = threading.Lock()
_SCHEDULE_STATE = threading.local()
_SCHEDULE_STATS_LOCK = threading.Lock()
_SCHEDULE_STATS: dict[str, deque[dict[str, object]]] = defaultdict(lambda: deque(maxlen=200))


def _model_gate(model: str, digest: str) -> _PriorityModelGate:
    """Return the process-wide execution gate for one loaded model artifact.

    Role-local semaphores did not protect Ollama from a router, narrator and
    extractor reaching the same single-runner 14B model concurrently. Ollama
    then returned an immediate 500 and the storefront mislabeled a capable
    request as generic. The gate is keyed by artifact, not by application or
    prompt, and can be widened only for a runtime certified for parallel model
    execution.
    """
    try:
        limit = max(1, min(int(os.getenv("LOCAL_MODEL_MAX_CONCURRENCY", "1") or 1), 4))
    except (TypeError, ValueError):
        limit = 1
    key = f"{str(model).strip().casefold()}@{str(digest).strip().casefold()}:{limit}"
    with _MODEL_GATES_LOCK:
        return _MODEL_GATES.setdefault(key, _PriorityModelGate(limit))


def _role_priority(role: str) -> int:
    return int(_ROLE_PRIORITIES.get(str(role or "").strip(), 25))


def _record_schedule(metrics: dict[str, object]) -> None:
    _SCHEDULE_STATE.metrics = dict(metrics)
    with _SCHEDULE_STATS_LOCK:
        _SCHEDULE_STATS[str(metrics.get("role") or "unknown")].append(dict(metrics))


def last_local_model_schedule_metrics() -> dict[str, object]:
    """Return safe timing evidence for the current request thread."""

    return dict(getattr(_SCHEDULE_STATE, "metrics", {}) or {})


def local_model_scheduler_snapshot() -> dict[str, object]:
    """Bounded process-local p50/p90 timing and outcome counts by role."""

    with _SCHEDULE_STATS_LOCK:
        rows = {role: list(samples) for role, samples in _SCHEDULE_STATS.items()}
    result: dict[str, object] = {}
    for role, samples in rows.items():
        queue = sorted(float(item.get("queue_ms") or 0.0) for item in samples)
        execution = sorted(float(item.get("execution_ms") or 0.0) for item in samples)

        def percentile(values: list[float], fraction: float) -> float:
            if not values:
                return 0.0
            index = min(len(values) - 1, max(0, int(round((len(values) - 1) * fraction))))
            return round(values[index], 2)

        result[role] = {
            "samples": len(samples),
            "priority": _role_priority(role),
            "queue_p50_ms": percentile(queue, 0.5),
            "queue_p90_ms": percentile(queue, 0.9),
            "execution_p50_ms": percentile(execution, 0.5),
            "execution_p90_ms": percentile(execution, 0.9),
            "last_status": str(samples[-1].get("status") or "unknown"),
        }
    return {"roles": result, "policy": "local-model-priority-v1"}


def _reset_local_model_scheduler_for_tests() -> None:
    with _MODEL_GATES_LOCK:
        _MODEL_GATES.clear()
    with _SCHEDULE_STATS_LOCK:
        _SCHEDULE_STATS.clear()
    _SCHEDULE_STATE.metrics = {}


def execute_local_model_role(
    prompt: str,
    *,
    role: str,
    purpose: str,
    prompt_id: str,
    model: str,
    digest: str,
    timeout_s: float,
    max_output_tokens: int,
    tenant_id: str = "portfolio-demo",
    context_hash: str | None = None,
    transport: Transport | None = None,
) -> str:
    """Return model text or raise a typed runtime failure; never fall back to cloud."""

    schedule_started = time.perf_counter()
    deadline = schedule_started + max(float(timeout_s), 0.05)
    priority = _role_priority(role)
    from src.app.services.ollama_endpoint import normalize_ollama_url

    base_url = normalize_ollama_url(
        os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    )
    expected = str(digest or "").strip().lower()
    fixture = transport is not None and expected == "0" * 64
    verification_status = "test_fixture" if fixture else verify_ollama_artifact(
        base_url=base_url, model=model, expected_digest=expected,
        timeout_s=min(max(timeout_s, 0.1), 2.0),
    ).status
    if verification_status not in {"verified", "test_fixture"}:
        from src.app.observability.pilot_runtime_metrics import record_model_outcome

        record_model_outcome(
            "blocked", f"model_artifact_{verification_status}", 0,
        )
        raise RuntimeError(f"model_artifact_{verification_status}")
    endpoint = base_url + "/api/generate"
    host = str(urlsplit(endpoint).hostname or "")
    deployment_id = f"local-{role.replace('_', '-')}-{sha256_text(model)[:10]}"
    deployment = ModelDeployment(
        deployment_id=deployment_id, provider="ollama", endpoint=endpoint,
        endpoint_identity=host, model_artifact_id=f"{model}@sha256:{expected[:12]}",
        model_artifact_digest=expected, artifact_verification_status=verification_status,
        jurisdiction="local-development", locality="loopback", allowed_roles={role},
        allowed_data_classes={"buyer_workload", "public_catalog", "aggregate_market"},
        allowed_capabilities=set(), retention_policy="no-provider-retention",
        training_policy="disabled", policy_version="local-model-role-v1",
    )
    # Specialized role transports (for example strict JSON output) still need
    # the durable ledger. Only an explicit all-zero-digest test fixture uses
    # the gateway's in-memory ledger.
    ledger = None if fixture else application_agent_run_ledger()
    gate = _model_gate(model, expected)
    queue_allowance = max(0.0, deadline - time.perf_counter())
    acquired, queue_ms = gate.acquire(priority=priority, timeout=queue_allowance)
    if not acquired:
        _record_schedule({
            "role": role, "priority": priority, "status": "timed_out",
            "failure_code": "local_model_queue_timeout", "queue_ms": round(queue_ms, 2),
            "execution_ms": 0.0, "deadline_ms": round(max(float(timeout_s), 0.05) * 1_000),
            "cancelled": True,
        })
        raise RuntimeError("local_model_queue_timeout")
    remaining = deadline - time.perf_counter()
    if remaining <= 0:
        gate.release()
        _record_schedule({
            "role": role, "priority": priority, "status": "timed_out",
            "failure_code": "local_model_deadline_exhausted", "queue_ms": round(queue_ms, 2),
            "execution_ms": 0.0, "deadline_ms": round(max(float(timeout_s), 0.05) * 1_000),
            "cancelled": True,
        })
        raise RuntimeError("local_model_deadline_exhausted")
    request = ModelExecutionRequest(
        tenant_id=tenant_id, purpose=purpose, role=role,
        deployment_id=deployment.deployment_id,
        model_artifact_id=deployment.model_artifact_id,
        prompt_id=prompt_id, prompt_version="v1", prompt_hash=sha256_text(prompt),
        context_hash=context_hash or sha256_text(f"{purpose}:{tenant_id}"),
        data_classes={
            "aggregate_market" if role == "market_narrator" else "buyer_workload"
        },
        timeout_ms=round(min(max(remaining, 0.05), 120.0) * 1_000),
        max_output_tokens=max_output_tokens,
        scheduler_queue_ms=round(queue_ms, 2),
        scheduler_deadline_ms=round(max(float(timeout_s), 0.05) * 1_000),
    )
    execution_started = time.perf_counter()
    result = None
    execution_error: BaseException | None = None
    try:
        result = ModelExecutionGateway(
            [deployment], **({"ledger": ledger} if ledger is not None else {}),
        ).execute(
            request, prompt=prompt, transport=transport or ollama_generate_transport,
        )
    except BaseException as exc:
        execution_error = exc
    finally:
        gate.release()
        execution_ms = (time.perf_counter() - execution_started) * 1_000
    status = (
        "completed"
        if execution_error is None and result is not None and result.status == "completed"
        else "failed"
    )
    failure_code = None if status == "completed" else (
        (type(execution_error).__name__ if execution_error is not None else None)
        or getattr(result, "failure_code", None)
        or getattr(result, "status", None)
        or "model_execution_failed"
    )
    _record_schedule({
        "role": role, "priority": priority, "status": status,
        "failure_code": failure_code, "queue_ms": round(queue_ms, 2),
        "execution_ms": round(execution_ms, 2),
        "deadline_ms": round(max(float(timeout_s), 0.05) * 1_000),
        "cancelled": False,
    })
    if execution_error is not None:
        raise execution_error
    if result.status != "completed" or result.text is None:
        raise RuntimeError(result.failure_code or result.status)
    return result.text


def configured_digest(*names: str) -> str:
    for name in names:
        value = str(os.getenv(name) or "").strip().lower()
        if value:
            return value
    return ""


__all__ = [
    "configured_digest", "execute_local_model_role",
    "last_local_model_schedule_metrics", "local_model_scheduler_snapshot",
]
