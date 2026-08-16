"""Reusable Ollama-only role execution behind ModelExecutionGateway."""
from __future__ import annotations

import os
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

    base_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    expected = str(digest or "").strip().lower()
    fixture = transport is not None and expected == "0" * 64
    verification_status = "test_fixture" if fixture else verify_ollama_artifact(
        base_url=base_url, model=model, expected_digest=expected,
        timeout_s=min(max(timeout_s, 0.1), 2.0),
    ).status
    if verification_status not in {"verified", "test_fixture"}:
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
    request = ModelExecutionRequest(
        tenant_id=tenant_id, purpose=purpose, role=role,
        deployment_id=deployment.deployment_id,
        model_artifact_id=deployment.model_artifact_id,
        prompt_id=prompt_id, prompt_version="v1", prompt_hash=sha256_text(prompt),
        context_hash=context_hash or sha256_text(f"{purpose}:{tenant_id}"),
        data_classes={
            "aggregate_market" if role == "market_narrator" else "buyer_workload"
        },
        timeout_ms=round(min(max(timeout_s, 0.05), 120.0) * 1_000),
        max_output_tokens=max_output_tokens,
    )
    ledger = (
        application_agent_run_ledger()
        if transport is None else None
    )
    result = ModelExecutionGateway(
        [deployment], **({"ledger": ledger} if ledger is not None else {}),
    ).execute(
        request, prompt=prompt, transport=transport or ollama_generate_transport,
    )
    if result.status != "completed" or result.text is None:
        raise RuntimeError(result.failure_code or result.status)
    return result.text


def configured_digest(*names: str) -> str:
    for name in names:
        value = str(os.getenv(name) or "").strip().lower()
        if value:
            return value
    return ""


__all__ = ["configured_digest", "execute_local_model_role"]
