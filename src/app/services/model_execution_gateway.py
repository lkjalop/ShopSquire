"""Single policy boundary for model execution.

Application code supplies an enrolled deployment plus a transport callback.  The
gateway validates identity, purpose, data handling and capabilities; bounds the
wait; records sanitized append-only events; and never performs an implicit
provider fallback.  It grants no commerce authority.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.security.provider_boundary import sanitize_for_provider
from src.app.security.dlp_export import dlp_scrub_all


_COMMERCE_CAPABILITIES = frozenset({
    "cart_mutation", "rfq_send", "payment", "shipment", "supplier_email_send",
})
_EXECUTION_SLOTS = threading.BoundedSemaphore(value=8)
AgentRunEventType = Literal[
    "accepted", "blocked", "completed", "failed", "timeout", "cancelled",
    "late_result_quarantined", "replayed",
]


def sha256_text(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


class ModelDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=80)
    endpoint: str = Field(min_length=1, max_length=500)
    endpoint_identity: str = Field(min_length=1, max_length=240)
    model_artifact_id: str = Field(min_length=1, max_length=240)
    model_artifact_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    jurisdiction: str = Field(min_length=1, max_length=80)
    locality: Literal["loopback", "private", "cloud"]
    allowed_roles: set[str] = Field(min_length=1)
    allowed_data_classes: set[str] = Field(default_factory=set)
    allowed_capabilities: set[str] = Field(default_factory=set)
    retention_policy: str = Field(min_length=1, max_length=160)
    training_policy: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=160)
    artifact_verification_status: Literal["verified", "test_fixture", "unverified"] = "unverified"
    enabled: bool = True

    @model_validator(mode="after")
    def validate_endpoint_identity(self) -> "ModelDeployment":
        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("deployment_endpoint_invalid")
        host = parsed.hostname.lower()
        if self.endpoint_identity.lower() != host:
            raise ValueError("deployment_endpoint_identity_mismatch")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if self.locality == "loopback" and not (
            host == "localhost" or address is not None and address.is_loopback
        ):
            raise ValueError("loopback_deployment_not_loopback")
        if self.locality == "private" and not (
            address is not None and (address.is_private or address.is_loopback)
        ):
            raise ValueError("private_deployment_not_private")
        if self.allowed_capabilities & _COMMERCE_CAPABILITIES:
            raise ValueError("model_deployment_cannot_have_commerce_capability")
        return self


class ModelExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: f"model-run-{uuid.uuid4().hex}")
    tenant_id: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=80)
    deployment_id: str = Field(min_length=1, max_length=160)
    model_artifact_id: str = Field(min_length=1, max_length=240)
    prompt_id: str = Field(min_length=1, max_length=160)
    prompt_version: str = Field(min_length=1, max_length=160)
    prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    context_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    data_classes: set[str] = Field(default_factory=set)
    requested_capabilities: set[str] = Field(default_factory=set)
    timeout_ms: int = Field(default=8_000, ge=50, le=120_000)
    max_output_tokens: int = Field(default=512, ge=1, le=8_192)
    fallback_policy: Literal["no_fallback"] = "no_fallback"


class AgentRunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    run_id: str
    tenant_id: str
    event_type: AgentRunEventType
    occurred_at_ms: int
    deployment_id: str
    model_artifact_id: str
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    context_hash: str
    policy_version: str
    details: dict[str, Any] = Field(default_factory=dict)
    commercial_authority: Literal[False] = False


@dataclass
class AgentRunEventLedger:
    """Thread-safe append-only ledger containing hashes and bounded metadata only."""

    _events: list[AgentRunEvent] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, request: ModelExecutionRequest, deployment: ModelDeployment,
               event_type: AgentRunEventType,
               **details: Any) -> AgentRunEvent:
        safe_details = sanitize_agent_event_details(details)
        with self._lock:
            event = AgentRunEvent(
                sequence=len(self._events) + 1,
                run_id=request.run_id,
                tenant_id=request.tenant_id,
                event_type=event_type,
                occurred_at_ms=int(time.time() * 1_000),
                deployment_id=deployment.deployment_id,
                model_artifact_id=deployment.model_artifact_id,
                prompt_id=request.prompt_id,
                prompt_version=request.prompt_version,
                prompt_hash=request.prompt_hash,
                context_hash=request.context_hash,
                policy_version=deployment.policy_version,
                details=json.loads(json.dumps(safe_details, default=str)),
            )
            self._events.append(event)
            return event

    def events_for(self, run_id: str, *, tenant_id: str) -> tuple[AgentRunEvent, ...]:
        with self._lock:
            return tuple(event.model_copy(deep=True) for event in self._events
                         if event.run_id == run_id and event.tenant_id == tenant_id)


def sanitize_agent_event_details(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_agent_event_details(item)
            for key, item in value.items()
            if str(key).lower() not in {
                "prompt", "context", "raw_input", "raw_output", "buyer_address",
            }
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_agent_event_details(item) for item in value[:64]]
    if isinstance(value, str):
        scrubbed, _hits = dlp_scrub_all(value[:2_000])
        return scrubbed
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return type(value).__name__


@dataclass(frozen=True)
class ModelExecutionResult:
    status: Literal["completed", "blocked", "timeout", "cancelled", "failed"]
    run_id: str
    text: str | None
    output_hash: str | None
    elapsed_ms: int
    failure_code: str | None
    late_result_quarantined: bool
    dlp_hits: int
    commercial_authority_granted: Literal[False] = False


Transport = Callable[[str, ModelDeployment, ModelExecutionRequest], str]


class ModelExecutionGateway:
    """Resolve only pre-enrolled deployments before invoking the execution boundary."""

    def __init__(
        self,
        deployments: list[ModelDeployment],
        *,
        ledger: AgentRunEventLedger | None = None,
        allowed_providers: set[str] | None = None,
    ):
        indexed = {deployment.deployment_id: deployment for deployment in deployments}
        if len(indexed) != len(deployments):
            raise ValueError("duplicate_model_deployment_id")
        allowed = {value.lower() for value in (allowed_providers or {"ollama"})}
        prohibited = sorted({row.provider.lower() for row in deployments} - allowed)
        if prohibited:
            raise ValueError(f"model_provider_not_allowed:{','.join(prohibited)}")
        self._deployments = indexed
        self.ledger = ledger or AgentRunEventLedger()

    def execute(
        self, request: ModelExecutionRequest, *, prompt: str, transport: Transport,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> ModelExecutionResult:
        deployment = self._deployments.get(request.deployment_id)
        if deployment is None:
            raise ValueError("model_deployment_not_enrolled")
        return execute_model(
            request, deployment, prompt=prompt, transport=transport,
            ledger=self.ledger, cancellation_requested=cancellation_requested,
        )


def execute_model(
    request: ModelExecutionRequest,
    deployment: ModelDeployment,
    *,
    prompt: str,
    transport: Transport,
    ledger: AgentRunEventLedger,
    cancellation_requested: Callable[[], bool] | None = None,
) -> ModelExecutionResult:
    """Execute one enrolled deployment with no implicit fallback or side effects."""

    started = time.monotonic()

    from src.app.observability.pilot_runtime_metrics import (
        agent_ledger_persistence_failures_total,
        model_late_results_total,
        record_model_outcome,
    )

    def append_event(event_type: AgentRunEventType, **details: Any) -> bool:
        try:
            ledger.append(request, deployment, event_type, **details)
            return True
        except Exception:
            agent_ledger_persistence_failures_total.inc()
            return False

    def finish(status: str, *, text: str | None = None, failure: str | None = None,
               late: bool = False, dlp_hits: int = 0) -> ModelExecutionResult:
        result = ModelExecutionResult(
            status=status, run_id=request.run_id, text=text,
            output_hash=sha256_text(text) if text is not None else None,
            elapsed_ms=round((time.monotonic() - started) * 1_000),
            failure_code=failure, late_result_quarantined=late, dlp_hits=dlp_hits,
        )
        record_model_outcome(result.status, result.failure_code, result.elapsed_ms)
        if result.late_result_quarantined:
            model_late_results_total.inc()
        return result

    block = None
    if not deployment.enabled:
        block = "deployment_disabled"
    elif request.deployment_id != deployment.deployment_id:
        block = "deployment_identity_mismatch"
    elif request.model_artifact_id != deployment.model_artifact_id:
        block = "model_artifact_identity_mismatch"
    elif deployment.artifact_verification_status == "unverified":
        block = "model_artifact_not_verified"
    elif request.role not in deployment.allowed_roles:
        block = "role_not_allowed"
    elif not request.data_classes.issubset(deployment.allowed_data_classes):
        block = "data_class_not_allowed"
    elif not request.requested_capabilities.issubset(deployment.allowed_capabilities):
        block = "capability_not_allowed"
    elif request.requested_capabilities & _COMMERCE_CAPABILITIES:
        block = "commerce_capability_prohibited"
    elif sha256_text(prompt) != request.prompt_hash:
        block = "prompt_hash_mismatch"
    if block:
        append_event("blocked", failure_code=block)
        return finish("blocked", failure=block)
    if cancellation_requested and cancellation_requested():
        append_event("cancelled", failure_code="cancelled_before_dispatch")
        return finish("cancelled", failure="cancelled_before_dispatch")
    if not _EXECUTION_SLOTS.acquire(blocking=False):
        append_event("blocked", failure_code="gateway_capacity_exhausted")
        return finish("blocked", failure="gateway_capacity_exhausted")

    try:
        outbound_prompt, dlp_hits, _ = sanitize_for_provider(
            deployment.provider, prompt, data_categories=request.data_classes,
        )
    except Exception as exc:
        _EXECUTION_SLOTS.release()
        failure = f"provider_policy_blocked:{type(exc).__name__}"
        append_event("blocked", failure_code=failure)
        return finish("blocked", failure=failure)

    if not append_event("accepted", dlp_hits=dlp_hits):
        _EXECUTION_SLOTS.release()
        return finish("blocked", failure="agent_ledger_persistence_failed")
    result: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    quarantine_late_result = threading.Event()

    def invoke() -> None:
        try:
            value = transport(str(outbound_prompt), deployment, request)
            if quarantine_late_result.is_set():
                append_event(
                    "late_result_quarantined",
                    output_hash=sha256_text(str(value or "")),
                )
            result.put_nowait(("completed", value))
        except BaseException as exc:
            try:
                result.put_nowait(("failed", exc))
            except queue.Full:
                pass
        finally:
            _EXECUTION_SLOTS.release()

    worker = threading.Thread(target=invoke, name="shopsquire-model-gateway", daemon=True)
    try:
        worker.start()
    except BaseException:
        _EXECUTION_SLOTS.release()
        raise
    deadline = started + request.timeout_ms / 1_000.0
    while True:
        if cancellation_requested and cancellation_requested():
            quarantine_late_result.set()
            append_event("cancelled", late_result_quarantined=worker.is_alive())
            return finish("cancelled", failure="model_execution_cancelled",
                          late=worker.is_alive(), dlp_hits=dlp_hits)
        try:
            status, value = result.get(timeout=min(0.01, max(0.001, deadline - time.monotonic())))
        except queue.Empty:
            if time.monotonic() >= deadline:
                quarantine_late_result.set()
                append_event("timeout", late_result_quarantined=worker.is_alive())
                return finish("timeout", failure="model_execution_timeout",
                              late=worker.is_alive(), dlp_hits=dlp_hits)
            continue
        if status == "failed":
            append_event("failed", error_type=type(value).__name__)
            return finish("failed", failure=f"transport_failed:{type(value).__name__}",
                          dlp_hits=dlp_hits)
        text = str(value or "")
        if not append_event("completed", output_hash=sha256_text(text)):
            return finish("failed", failure="agent_ledger_persistence_failed", dlp_hits=dlp_hits)
        return finish("completed", text=text, dlp_hits=dlp_hits)


__all__ = [
    "AgentRunEvent", "AgentRunEventLedger", "ModelDeployment", "ModelExecutionRequest",
    "ModelExecutionGateway", "ModelExecutionResult", "execute_model",
    "sanitize_agent_event_details", "sha256_text",
]
