"""Guarded, buyer-triggered local-model preview over deterministic shelf copy."""
from __future__ import annotations

import os
import json
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.model_execution_gateway import (
    AgentRunEventLedger,
    ModelDeployment,
    ModelExecutionGateway,
    ModelExecutionRequest,
    sha256_text,
)
from src.app.services.model_transports import ollama_generate_transport
from src.app.services.ollama_artifact_verification import verify_ollama_artifact
from src.app.services.agent_run_event_store import application_agent_run_ledger
from src.app.services.recommendation_core.workload_narration_shadow import run_shadow_narration


class ProductNarrationSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=120)
    sentence: str = Field(min_length=1, max_length=800)
    evidence_basis: str = Field(min_length=1, max_length=40)


class ShelfNarrationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: str = Field(min_length=1, max_length=500)
    accepted_requirements: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    shelf_summary: str = Field(min_length=1, max_length=1200)
    top_product_sentences: list[ProductNarrationSentence] = Field(max_length=3)
    reranking_summary: str = Field(min_length=1, max_length=1200)


def deterministic_preview(projection: ShelfNarrationProjection) -> str:
    blocks = [projection.shelf_summary]
    blocks.extend(row.sentence for row in projection.top_product_sentences[:3])
    blocks.append(projection.reranking_summary)
    return " ".join(dict.fromkeys(value.strip() for value in blocks if value.strip()))


def render_portfolio_narration_preview(
    projection: ShelfNarrationProjection,
    *,
    generate: Callable[[str], str] | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    fallback = deterministic_preview(projection)
    active = (
        os.getenv("PORTFOLIO_LOCAL_NARRATION_PREVIEW_ENABLED", "0").strip().lower()
        in {"1", "true", "yes", "on"}
    ) if enabled is None else enabled
    if not active:
        return {
            "status": "deterministic_fallback", "renderer": "deterministic",
            "text": fallback, "fallback_reason": "preview_disabled", "violations": [],
            "buyer_visible_model_copy": False, "commercial_authority_granted": False,
        }
    model = os.getenv("PORTFOLIO_NARRATION_MODEL", "qwen3:14b")
    try:
        timeout = min(8.0, max(1.0, float(os.getenv("PORTFOLIO_NARRATION_TIMEOUT_SEC", "6"))))
    except ValueError:
        timeout = 6.0

    artifact_digest = str(os.getenv("PORTFOLIO_NARRATION_MODEL_DIGEST") or "").lower()
    if generate is not None and len(artifact_digest) != 64:
        artifact_digest = "0" * 64
    base_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    endpoint = base_url + "/api/generate"
    endpoint_host = endpoint.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    verification_status = "test_fixture" if generate is not None else "unverified"
    if generate is None and len(artifact_digest) == 64:
        verification_status = verify_ollama_artifact(
            base_url=base_url, model=model, expected_digest=artifact_digest,
        ).status
    try:
        deployment = ModelDeployment(
            deployment_id="portfolio-local-narrator",
            provider="ollama", endpoint=endpoint, endpoint_identity=endpoint_host,
            model_artifact_id=f"{model}@sha256:{artifact_digest[:12]}",
            model_artifact_digest=artifact_digest,
            jurisdiction="local-development", locality="loopback",
            allowed_roles={"narrator"},
            allowed_data_classes={"public_catalog", "buyer_workload"},
            allowed_capabilities=set(), retention_policy="no-provider-retention",
            training_policy="disabled", policy_version="portfolio-narration-v1",
            artifact_verification_status=verification_status,
        )
    except Exception as exc:
        return {
            "status": "deterministic_fallback", "renderer": "deterministic",
            "text": fallback, "fallback_reason": f"deployment_not_enrolled:{type(exc).__name__}",
            "violations": [], "buyer_visible_model_copy": False,
            "commercial_authority_granted": False,
        }
    ledger = AgentRunEventLedger() if generate is not None else application_agent_run_ledger()
    gateway = ModelExecutionGateway([deployment], ledger=ledger)
    context_hash = sha256_text(json.dumps(projection.model_dump(mode="json"), sort_keys=True))

    def local_generate(prompt: str) -> str:
        bounded_prompt = prompt + "\n/no_think"
        request = ModelExecutionRequest(
            tenant_id="portfolio-demo", purpose="evidence_narration", role="narrator",
            deployment_id=deployment.deployment_id,
            model_artifact_id=deployment.model_artifact_id,
            prompt_id="portfolio-shelf-narration", prompt_version="v1",
            prompt_hash=sha256_text(bounded_prompt), context_hash=context_hash,
            data_classes={"public_catalog", "buyer_workload"},
            timeout_ms=round(timeout * 1_000), max_output_tokens=180,
        )
        transport = (
            (lambda sent, _deployment, _request: generate(sent))
            if generate is not None else ollama_generate_transport
        )
        result = gateway.execute(request, prompt=bounded_prompt, transport=transport)
        if result.status != "completed" or result.text is None:
            raise RuntimeError(result.failure_code or result.status)
        return result.text

    authorized = [projection.shelf_summary]
    authorized.extend(row.sentence for row in projection.top_product_sentences[:3])
    authorized.append(projection.reranking_summary)
    decision = {
        "schema_version": "portfolio-shelf-narration-preview-v1",
        "workload": {"name": projection.purpose, "material_unknowns": []},
        "overall_decision": "unresolved",
        "authorized_narration_blocks": [{"text": text} for text in authorized],
        "material_preservation": [
            {"requirement_id": f"block-{index}", "required_terms": [text]}
            for index, text in enumerate(authorized)
        ],
        "fit_ledger": [], "supplier_choices": [],
    }
    shadow = run_shadow_narration(
        decision, generate=local_generate, model_id=model,
    )
    accepted = shadow.get("status") == "accepted_shadow" and bool(shadow.get("candidate"))
    return {
        "status": "accepted_preview" if accepted else "deterministic_fallback",
        "renderer": "local_model_preview" if accepted else "deterministic",
        "text": shadow.get("candidate") if accepted else fallback,
        "fallback_reason": None if accepted else str(shadow.get("status") or "preview_failed"),
        "violations": list(shadow.get("violations") or []),
        "elapsed_ms": int(shadow.get("elapsed_ms") or 0), "model_id": model,
        "buyer_visible_model_copy": bool(accepted),
        "commercial_authority_granted": False,
    }


__all__ = [
    "ShelfNarrationProjection", "deterministic_preview", "render_portfolio_narration_preview",
]
