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
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.app.services.case_research_plan import CaseDiscoveryQuery, CaseResearchPlan
from src.app.services.agent_run_event_store import application_agent_run_ledger
from src.app.services.model_execution_gateway import (
    ModelDeployment,
    ModelExecutionGateway,
    ModelExecutionRequest,
    sha256_text,
)
from src.app.services.model_transports import make_ollama_generate_transport
from src.app.services.ollama_artifact_verification import verify_ollama_artifact


Axis = Literal[
    "concept_and_software", "requirements_and_compatibility", "support_and_constraints",
]
_WORD = re.compile(r"[a-z0-9]+")
_URL = re.compile(r"(?:https?://|\bsite:|\bwww\.)", re.IGNORECASE)
_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_HARDWARE_FLOOR = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:gb|tb|cores?|hz|watts?|w)\b", re.IGNORECASE,
)
_FILLER = {
    "a", "an", "and", "are", "can", "could", "for", "from", "handle", "i", "in",
    "is", "it", "laptop", "machine", "need", "not", "of", "only", "or", "run",
    "something", "system", "the", "this", "to", "we", "what", "which", "will", "with",
}
_SHADOW_LOCK = Lock()
_SHADOW_FUTURES: dict[str, Future[tuple[CaseResearchPlan, dict[str, Any]]]] = {}
_SHADOW_MAX_PENDING = 1
_SHADOW_MAX_RETAINED = 64


def _submit_shadow(
    plan: CaseResearchPlan,
) -> Future[tuple[CaseResearchPlan, dict[str, Any]]]:
    """Submit one bounded task and release its worker after completion."""

    executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="open-world-query-shadow",
    )
    future = executor.submit(propose_open_world_queries, plan, timeout_s=6.0)
    future.add_done_callback(lambda _completed: executor.shutdown(wait=False))
    return future


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
    publisher_domain_hypotheses: list[str] = Field(default_factory=list, max_length=2)
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
        "interpretations, shared_concepts, divergent_axes, and 2-3 search queries. Every one of "
        "interpretations, shared_concepts, and divergent_axes must be a JSON array of strings. Queries must "
        "cover distinct axes selected from concept_and_software, requirements_and_compatibility, "
        "support_and_constraints. Expand acronyms and domain terminology when useful. Do not name "
        "a vendor unless the buyer named it. If the buyer named a publisher or product, include up "
        "to two likely registrable publisher domains in publisher_domain_hypotheses; otherwise use [] . "
        "Domains are untrusted discovery hints only. Do not include URLs, site: filters, prices, hardware "
        "numbers, products, or claims. Search is discovery only and establishes no authority.\n"
        f"Buyer outcome: {purpose!r}\n"
        "JSON schema: {interpretations:[string],shared_concepts:[string],divergent_axes:[string],"
        "publisher_domain_hypotheses:[string],"
        "queries:[{axis:string,query:string}]}"
    )


def _ollama_call(prompt: str, timeout_s: float) -> str:
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OPEN_WORLD_QUERY_MODEL", "granite4:micro")
    digest = str(os.getenv("OPEN_WORLD_QUERY_MODEL_DIGEST") or "").lower()
    verification = verify_ollama_artifact(
        base_url=base, model=model, expected_digest=digest,
        timeout_s=min(timeout_s, 2.0),
    )
    if verification.status != "verified":
        raise RuntimeError(verification.error_code or verification.status)
    endpoint = base + "/api/generate"
    host = endpoint.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    deployment = ModelDeployment(
        deployment_id="local-open-world-query-planner", provider="ollama",
        endpoint=endpoint, endpoint_identity=host,
        model_artifact_id=f"{model}@sha256:{digest[:12]}",
        model_artifact_digest=digest, artifact_verification_status="verified",
        jurisdiction="local-development", locality="loopback",
        allowed_roles={"query_planner"}, allowed_data_classes={"buyer_workload"},
        allowed_capabilities=set(), retention_policy="no-provider-retention",
        training_policy="disabled", policy_version="open-world-query-v1",
    )
    request = ModelExecutionRequest(
        tenant_id="portfolio-demo", purpose="open_world_discovery_query_planning",
        role="query_planner", deployment_id=deployment.deployment_id,
        model_artifact_id=deployment.model_artifact_id,
        prompt_id="open-world-query-proposal", prompt_version="v1",
        prompt_hash=sha256_text(prompt), context_hash=sha256_text("open-world-research"),
        data_classes={"buyer_workload"}, timeout_ms=round(timeout_s * 1_000),
        # This is a three-query routing artifact, not narration. A compact cap
        # keeps a prewarmed 14B local model inside the six-second worker budget.
        max_output_tokens=420,
    )
    transport = make_ollama_generate_transport(
        response_format="json", keep_alive="30m", think=False,
    )
    result = ModelExecutionGateway(
        [deployment], ledger=application_agent_run_ledger(),
    ).execute(request, prompt=prompt, transport=transport)
    if result.status != "completed" or result.text is None:
        raise RuntimeError(result.failure_code or result.status)
    return result.text


def propose_open_world_queries(
    plan: CaseResearchPlan,
    *,
    model_fn: Callable[[str, float], str] | None = None,
    timeout_s: float | None = None,
) -> tuple[CaseResearchPlan, dict[str, Any]]:
    """Return a validated proposal-enhanced plan or the original plan."""

    if plan.publisher_status != "unresolved":
        return plan, {"status": "not_applicable", "model_calls": 0}
    enabled = any(
        str(os.getenv(name, "0")).lower() in {"1", "true", "yes", "on"}
        for name in (
            "OPEN_WORLD_QUERY_PROPOSER_ENABLED",
            "OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED",
        )
    )
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
        # Small local models sometimes repeat a semantically reasonable axis.
        # The axis is routing metadata, so deterministically relabel duplicates
        # rather than discarding otherwise bounded queries.
        axis_order: list[Axis] = [
            "concept_and_software", "requirements_and_compatibility", "support_and_constraints",
        ]
        used_axes: set[Axis] = set()
        normalized_rows: list[ProposedDiscoveryQuery] = []
        for row in proposal.queries:
            axis = row.axis
            if axis in used_axes:
                axis = next(item for item in axis_order if item not in used_axes)
            used_axes.add(axis)
            normalized_rows.append(row.model_copy(update={"axis": axis}))
        buyer_terms = _terms(plan.retained_purpose)
        for row in normalized_rows:
            if _URL.search(row.query):
                raise ValueError("url_or_site_filter_not_allowed")
            if _HARDWARE_FLOOR.search(row.query) and not _HARDWARE_FLOOR.search(
                plan.retained_purpose
            ):
                raise ValueError("invented_hardware_floor")
            if not (_terms(row.query) & buyer_terms):
                raise ValueError("query_not_anchored_to_buyer_outcome")
        domain_hypotheses: list[str] = []
        for raw_domain in proposal.publisher_domain_hypotheses:
            domain = str(raw_domain or "").strip().lower().removeprefix("www.")
            domain_terms = _terms(domain.replace(".", " ").replace("-", " "))
            if not _DOMAIN.fullmatch(domain) or not (domain_terms & buyer_terms):
                continue
            if domain not in domain_hypotheses:
                domain_hypotheses.append(domain)
        queries = [
            CaseDiscoveryQuery(
                query_id=f"model_{index + 1}", axis=row.axis,
                query=" ".join(row.query.split()),
            )
            for index, row in enumerate(normalized_rows)
        ]
        if domain_hypotheses:
            subject = " ".join(sorted(buyer_terms, key=lambda token: (-len(token), token))[:4])
            origin_query = CaseDiscoveryQuery(
                query_id="model_origin", axis="support_and_constraints",
                query=f"site:{domain_hypotheses[0]} {subject} documentation requirements",
            )
            queries = [row for row in queries if row.axis != "support_and_constraints"][:2]
            queries.append(origin_query)
        proposal = proposal.model_copy(update={
            "queries": normalized_rows,
            "publisher_domain_hypotheses": domain_hypotheses,
        })
        return plan.model_copy(update={"discovery_queries": queries}), {
            "status": "accepted",
            "model_calls": 1,
            "model": os.getenv("OPEN_WORLD_QUERY_MODEL", "granite4:micro"),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "proposal": proposal.model_dump(mode="json"),
            "authority": "discovery_proposal_only",
        }
    except (
        TypeError,
        ValueError,
        ValidationError,
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        TimeoutError,
    ) as exc:
        return plan, {
            "status": "rejected_or_unavailable",
            "model_calls": 1,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "reason": type(exc).__name__,
            "authority": "none",
        }


def schedule_open_world_query_proposal(plan: CaseResearchPlan) -> dict[str, Any]:
    """Schedule advisory interpretation without delaying the buyer response."""

    enabled = str(os.getenv("OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED", "0")).lower() in {
        "1", "true", "yes", "on",
    }
    if not enabled or plan.publisher_status != "unresolved":
        return {"status": "disabled", "model_calls": 0, "authority": "none"}
    with _SHADOW_LOCK:
        existing = _SHADOW_FUTURES.get(plan.plan_id)
        if existing is not None:
            return {
                "status": "completed_shadow_available" if existing.done() else "scheduled_shadow",
                "model_calls": 0,
                "authority": "discovery_proposal_only",
            }
        if len(_SHADOW_FUTURES) >= _SHADOW_MAX_RETAINED:
            for stale_plan_id, stale_future in list(_SHADOW_FUTURES.items()):
                if stale_future.done():
                    _SHADOW_FUTURES.pop(stale_plan_id, None)
                if len(_SHADOW_FUTURES) < _SHADOW_MAX_RETAINED // 2:
                    break
        active = sum(not future.done() for future in _SHADOW_FUTURES.values())
        if active >= _SHADOW_MAX_PENDING:
            return {
                "status": "capacity_degraded",
                "model_calls": 0,
                "authority": "none",
                "reason": "shadow_capacity_reached",
            }
        _SHADOW_FUTURES[plan.plan_id] = _submit_shadow(plan)
    return {
        "status": "scheduled_shadow",
        "model_calls": 0,
        "authority": "discovery_proposal_only",
    }


def consume_open_world_query_proposal(
    plan: CaseResearchPlan,
) -> tuple[CaseResearchPlan, dict[str, Any]]:
    """Use a completed shadow result; never wait for one in the request path."""

    with _SHADOW_LOCK:
        future = _SHADOW_FUTURES.get(plan.plan_id)
    if future is None:
        scheduled = schedule_open_world_query_proposal(plan)
        return plan, scheduled
    if not future.done():
        return plan, {
            "status": "scheduled_shadow",
            "model_calls": 0,
            "authority": "discovery_proposal_only",
            "reason": "deterministic_plan_used_without_waiting",
        }
    with _SHADOW_LOCK:
        _SHADOW_FUTURES.pop(plan.plan_id, None)
    try:
        proposed, receipt = future.result(timeout=0)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        return plan, {
            "status": "rejected_or_unavailable",
            "model_calls": 1,
            "authority": "none",
            "reason": type(exc).__name__,
        }
    return proposed, {**receipt, "status": f"{receipt['status']}_shadow"}


__all__ = [
    "OpenWorldQueryProposal", "consume_open_world_query_proposal",
    "propose_open_world_queries", "schedule_open_world_query_proposal",
]
