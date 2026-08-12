"""Local-model proposal for open-world discovery queries.

The model may improve vocabulary and split the buyer outcome into bounded search
axes. It cannot establish requirements, select a publisher, rank products, or
authorize commerce. Deterministic validation and the original plan remain the
fallback for every error or timeout.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.app.services.case_research_plan import CaseDiscoveryQuery, CaseResearchPlan


Axis = Literal[
    "concept_and_software", "requirements_and_compatibility", "support_and_constraints",
]
_WORD = re.compile(r"[a-z0-9]+")
_URL = re.compile(r"(?:https?://|\bsite:|\bwww\.)", re.IGNORECASE)
_HARDWARE_FLOOR = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:gb|tb|cores?|hz|watts?|w)\b", re.IGNORECASE,
)
_FILLER = {
    "a", "an", "and", "are", "can", "could", "for", "from", "handle", "i", "in",
    "is", "it", "laptop", "machine", "need", "not", "of", "only", "or", "run",
    "something", "system", "the", "this", "to", "we", "what", "which", "will", "with",
}


class ProposedDiscoveryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis: Axis
    query: str = Field(min_length=3, max_length=500)


class OpenWorldQueryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["open-world-query-proposal-v1"] = "open-world-query-proposal-v1"
    interpretations: list[str] = Field(min_length=1, max_length=3)
    shared_concepts: list[str] = Field(min_length=1, max_length=8)
    divergent_axes: list[str] = Field(default_factory=list, max_length=4)
    queries: list[ProposedDiscoveryQuery] = Field(min_length=2, max_length=3)
    authority: Literal["discovery_proposal_only"] = "discovery_proposal_only"


def _terms(value: str) -> set[str]:
    return {
        token for token in _WORD.findall(str(value or "").lower())
        if token not in _FILLER and (len(token) > 2 or any(char.isdigit() for char in token))
    }


def _prompt(purpose: str) -> str:
    return (
        "Return strict JSON only. Interpret an unfamiliar buyer workload for web discovery, "
        "without recommending hardware or inventing requirements. Produce 1-3 plausible "
        "interpretations, shared_concepts, divergent_axes, and 2-3 search queries. Queries must "
        "cover distinct axes selected from concept_and_software, requirements_and_compatibility, "
        "support_and_constraints. Expand acronyms and domain terminology when useful. Do not name "
        "a vendor unless the buyer named it. Do not include URLs, site: filters, prices, hardware "
        "numbers, products, or claims. Search is discovery only and establishes no authority.\n"
        f"Buyer outcome: {purpose!r}\n"
        "JSON schema: {interpretations:[string],shared_concepts:[string],divergent_axes:[string],"
        "queries:[{axis:string,query:string}]}"
    )


def _ollama_call(prompt: str, timeout_s: float) -> str:
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OPEN_WORLD_QUERY_MODEL", "qwen3:14b")
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "options": {"temperature": 0, "num_predict": 600},
    }
    if "qwen3" in model.lower():
        payload["think"] = False
    response = httpx.post(f"{base}/api/generate", json=payload, timeout=timeout_s)
    response.raise_for_status()
    return str((response.json() or {}).get("response") or "")


def propose_open_world_queries(
    plan: CaseResearchPlan,
    *,
    model_fn: Callable[[str, float], str] | None = None,
    timeout_s: float | None = None,
) -> tuple[CaseResearchPlan, dict[str, Any]]:
    """Return a validated proposal-enhanced plan or the original plan."""

    if plan.publisher_status != "unresolved":
        return plan, {"status": "not_applicable", "model_calls": 0}
    enabled = str(os.getenv("OPEN_WORLD_QUERY_PROPOSER_ENABLED", "0")).lower() in {
        "1", "true", "yes", "on",
    }
    if not enabled and model_fn is None:
        return plan, {"status": "disabled", "model_calls": 0}
    budget = max(1.0, min(float(timeout_s or 6.0), 10.0))
    started = time.monotonic()
    try:
        raw = (model_fn or _ollama_call)(_prompt(plan.retained_purpose), budget)
        data = json.loads(raw)
        data["schema_version"] = "open-world-query-proposal-v1"
        data["authority"] = "discovery_proposal_only"
        proposal = OpenWorldQueryProposal.model_validate(data)
        axes = [row.axis for row in proposal.queries]
        if len(set(axes)) != len(axes):
            raise ValueError("duplicate_query_axis")
        buyer_terms = _terms(plan.retained_purpose)
        for row in proposal.queries:
            if _URL.search(row.query):
                raise ValueError("url_or_site_filter_not_allowed")
            if _HARDWARE_FLOOR.search(row.query) and not _HARDWARE_FLOOR.search(
                plan.retained_purpose
            ):
                raise ValueError("invented_hardware_floor")
            if not (_terms(row.query) & buyer_terms):
                raise ValueError("query_not_anchored_to_buyer_outcome")
        queries = [
            CaseDiscoveryQuery(
                query_id=f"model_{index + 1}", axis=row.axis,
                query=" ".join(row.query.split()),
            )
            for index, row in enumerate(proposal.queries)
        ]
        return plan.model_copy(update={"discovery_queries": queries}), {
            "status": "accepted",
            "model_calls": 1,
            "model": os.getenv("OPEN_WORLD_QUERY_MODEL", "qwen3:14b"),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "proposal": proposal.model_dump(mode="json"),
            "authority": "discovery_proposal_only",
        }
    except (
        TypeError,
        ValueError,
        ValidationError,
        json.JSONDecodeError,
        httpx.HTTPError,
        OSError,
        TimeoutError,
    ) as exc:
        return plan, {
            "status": "rejected_or_unavailable",
            "model_calls": 1,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "reason": type(exc).__name__,
            "authority": "none",
        }


__all__ = ["OpenWorldQueryProposal", "propose_open_world_queries"]
