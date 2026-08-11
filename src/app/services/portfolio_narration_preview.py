"""Guarded, buyer-triggered local-model preview over deterministic shelf copy."""
from __future__ import annotations

import os
from typing import Any, Callable

import requests
from pydantic import BaseModel, ConfigDict, Field

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

    def local_generate(prompt: str) -> str:
        response = requests.post(
            os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/") + "/api/generate",
            json={
                "model": model, "prompt": prompt + "\n/no_think", "stream": False,
                "think": False, "keep_alive": "10m",
                "options": {"temperature": 0, "num_predict": 180},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return str(response.json().get("response") or "")

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
        decision, generate=generate or local_generate, model_id=model,
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
