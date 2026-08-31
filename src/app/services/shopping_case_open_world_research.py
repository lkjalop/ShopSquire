"""Case-bound orchestration for unresolved-publisher research.

This service deliberately stops after discovery and candidate persistence. Search
results are not requirements, and a discovered publisher has no qualification or
commerce authority until the separate approval/fetch/extraction path accepts it.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.case_publisher_candidate_workflow import persist_discovered_candidates
from src.app.services.case_research_plan import CaseResearchPlan
from src.app.services.commerce_feature_readiness import (
    external_search_readiness,
    record_external_research_runtime_observation,
)
from src.app.services.decision_log import log_trace_event
from src.app.services.official_source_governance import load_official_source_manifest
from src.app.services import open_world_research_discovery
from src.app.services.shopping_case_interpretation_jobs import (
    consume_completed_case_interpretation,
)
from src.app.services.shopping_case_research_contract import (
    project_research_execution_contract,
)
from src.app.services.shopping_case_truth_projection import ShoppingCaseTruthProjection


@dataclass(frozen=True)
class OpenWorldResearchUnavailable(Exception):
    code: str
    readiness: dict[str, Any]


async def _consume_interpretation_with_bounded_wait(
    db,
    *,
    tenant_id: str,
    case_id: str,
    case_revision: int,
    plan: CaseResearchPlan,
) -> tuple[CaseResearchPlan, dict[str, Any]]:
    """Wait briefly for the durable advisory plan, then fall back honestly."""

    try:
        wait_ms = int(os.getenv("OPEN_WORLD_QUERY_PLAN_WAIT_MS", "600") or 600)
    except (TypeError, ValueError):
        wait_ms = 600
    wait_ms = max(300, min(wait_ms, 800))
    deadline = time.monotonic() + wait_ms / 1_000.0
    while True:
        proposed, receipt = consume_completed_case_interpretation(
            db,
            tenant_id=tenant_id,
            case_id=case_id,
            case_revision=case_revision,
            plan=plan,
        )
        if receipt.get("status") not in {
            "queued", "running", "retry", "enqueue_degraded",
        } or time.monotonic() >= deadline:
            return proposed, {
                **receipt,
                "bounded_wait_ms": wait_ms,
                "fallback_used": receipt.get("status") != "completed_durable",
            }
        # End the current SQLite/PostgreSQL read transaction so the next poll
        # can observe the worker's revision-bound commit.
        db.rollback()
        await asyncio.sleep(0.05)


def _merge_governed_discovery_retry(
    primary: dict[str, Any], retry: dict[str, Any],
) -> dict[str, Any]:
    """Merge one model-planned retry without widening claim authority."""

    merged = dict(primary)
    candidates_by_url = {
        str(row.get("url")): dict(row)
        for row in [*(primary.get("candidates") or []), *(retry.get("candidates") or [])]
        if row.get("url")
    }
    merged["candidates"] = sorted(
        candidates_by_url.values(),
        key=lambda row: (-int(row.get("quality_score") or 0), str(row.get("url") or "")),
    )[:12]
    merged["receipts"] = [
        *(primary.get("receipts") or []), *(retry.get("receipts") or []),
    ]
    first_accounting = dict(primary.get("provider_accounting") or {})
    retry_accounting = dict(retry.get("provider_accounting") or {})
    merged["provider_accounting"] = {
        key: int(first_accounting.get(key) or 0) + int(retry_accounting.get(key) or 0)
        for key in ("discovery_calls", "external_calls", "official_origin_fetches", "paid_calls")
    }
    merged["status"] = (
        "publisher_candidates_found" if merged["candidates"]
        else retry.get("status") or primary.get("status")
    )
    merged["claims"] = []
    return merged


def _governed_domains() -> list[str]:
    return sorted({
        str(domain).strip().lower()
        for source in load_official_source_manifest().get("sources") or []
        if source.get("review_status") == "approved"
        for domain in source.get("allowed_domains") or []
        if str(domain).strip()
    })


async def execute_open_world_publisher_discovery_async(
    db: Session,
    *,
    plan: CaseResearchPlan,
    tenant_id: str,
    case_id: str,
    uid: str,
    search_url_template: str,
    runtime_status: dict[str, Any],
    candidate_configuration_ids: list[str],
    budget_cents: int | None,
    cancellation_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Discover and persist publisher candidates for one durable shopping case."""

    if plan.publisher_status != "unresolved":
        raise ValueError("open_world_plan_required")
    readiness = external_search_readiness(
        allowlist=_governed_domains(),
        tenant_id=tenant_id,
        runtime_status=runtime_status,
    )
    # A process-local failure observation is diagnostic, not a circuit breaker.
    # In the explicitly enrolled local demo profile, each new buyer-authorized
    # operation may make one bounded retry. Otherwise one transient SearXNG
    # startup miss disables discovery until the API process is restarted.
    if (
        not readiness.get("effective")
        and readiness.get("local_proof_enrolled")
        and readiness.get("error_code") in {
            "discovery_endpoint_unreachable", "discovery_endpoint_degraded",
        }
    ):
        readiness = {
            **readiness,
            "effective": True,
            "advisory_live": True,
            "capability_status": "bounded_retry_authorized",
            "reason": "prior runtime failure; this operation may retry once",
            "retrying_after_observed_failure": True,
        }
    if not readiness.get("effective"):
        raise OpenWorldResearchUnavailable(
            code=str(readiness.get("error_code") or "external_research_degraded"),
            readiness=readiness,
        )

    # Persist the hand-off before the first blocking provider call. Browser
    # disconnect certification waits for this event, then closes the buyer
    # transport so the request-scoped cancellation probe is deterministic.
    trace_id = case_id.removeprefix("sc-")
    log_trace_event(
        trace_id=trace_id,
        event_type="open_world_discovery_started",
        source_type="stage",
        source_id="SearXNG_Discovery",
        target_type="shopping_case",
        target_id=case_id,
        payload={
            "case_id": case_id,
            "execution_status": "started",
            "provider_accounting": {"external_calls": 0, "paid_calls": 0},
            "qualification_authority": "none",
            "cart_authority": "none",
        },
    )
    # The provider call below can block for its bounded transport deadline.
    # Commit this audit boundary so another connection (Decision Trace or the
    # disconnect-certification observer) can see that execution has started.
    db.commit()

    # Interpretation was durably scheduled with the provisional case. Consent
    # never waits: consume only a completed result for the current revision.
    from sqlalchemy import select
    from src.app.models.orm import ShoppingCase

    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id,
        ShoppingCase.case_id == case_id,
    )).scalar_one()
    discovery_plan, query_proposal = await _consume_interpretation_with_bounded_wait(
        db,
        tenant_id=tenant_id,
        case_id=case_id,
        case_revision=int(case.revision or 1),
        plan=plan,
    )
    discovery = await open_world_research_discovery.discover_open_world_publishers_async(
        discovery_plan,
        search_url_template=search_url_template,
        cancellation_requested=cancellation_requested,
    )
    # If deterministic discovery found no credible origin, consume a planner
    # that may have completed while those calls were in flight. Dispatch only
    # its first distinct query: total provider fan-out is capped at four.
    if not discovery.get("candidates") and not (discovery.get("cancellation") or {}).get("requested"):
        retry_plan, retry_proposal = await _consume_interpretation_with_bounded_wait(
            db,
            tenant_id=tenant_id,
            case_id=case_id,
            case_revision=int(case.revision or 1),
            plan=plan,
        )
        original_queries = [row.query for row in discovery_plan.discovery_queries]
        retry_queries = [
            row for row in retry_plan.discovery_queries if row.query not in original_queries
        ]
        if retry_proposal.get("status") == "completed_durable" and retry_queries:
            bounded_retry_plan = retry_plan.model_copy(update={
                "discovery_queries": retry_queries[:1],
            })
            retry_result = await open_world_research_discovery.discover_open_world_publishers_async(
                bounded_retry_plan,
                search_url_template=search_url_template,
                cancellation_requested=cancellation_requested,
            )
            discovery = _merge_governed_discovery_retry(discovery, retry_result)
            query_proposal = {
                **retry_proposal,
                "retry_dispatched": True,
                "retry_query_count": 1,
                "total_provider_fan_out": int(
                    (discovery.get("provider_accounting") or {}).get("external_calls") or 0
                ),
            }
    discovery["query_proposal"] = query_proposal
    # Discovery receipts prove dispatch/reachability, but discovered snippets
    # remain candidate metadata and can never compile as requirements.
    record_external_research_runtime_observation(discovery)
    persisted = persist_discovered_candidates(
        db,
        tenant_id=tenant_id,
        case_id=case_id,
        uid=uid,
        candidates=discovery["candidates"],
        receipts=discovery["receipts"],
    )
    persisted_by_url = {row.url: row for row in persisted}
    discovery["candidates"] = [
        {
            **candidate,
            "candidate_id": persisted_by_url[candidate["url"]].candidate_id,
            "candidate_version": persisted_by_url[candidate["url"]].version,
            "status": persisted_by_url[candidate["url"]].status,
            "approval_scope": persisted_by_url[candidate["url"]].approval_scope,
        }
        for candidate in discovery["candidates"]
        if candidate["url"] in persisted_by_url
    ]
    db.commit()

    shelves = project_accepted_catalog(
        db,
        accepted_claims=[],
        desired_outcome=plan.retained_purpose,
        budget_cents=budget_cents,
        tenant_id=tenant_id,
        candidate_configuration_ids=candidate_configuration_ids,
    ).model_dump(mode="json")
    accounting = discovery["provider_accounting"]
    contract = project_research_execution_contract(plan).model_dump(mode="json")
    discovery["research_plan_id"] = plan.plan_id
    discovery["execution_contract"] = contract
    exploration = ShoppingCaseTruthProjection.model_validate({
        "schema_version": "ambiguity-exploration-v1",
        "case_id": case_id,
        "trace_id": trace_id,
        "retained_purpose": plan.retained_purpose,
        "status": "unresolved",
        "interpretations": [row.model_dump(mode="json") for row in plan.hypotheses],
        "next_question": {"id": "publisher_scope", "text": plan.next_question},
        "research_choices": [
            "approve_discovered_source",
            "upload_requirements",
            "enter_specifications",
            "continue_provisionally",
        ],
        "execution": "live_discovery_completed",
        "evidence": "publisher_candidates_only",
        "decision": "provisional_exploration_only",
        "cart_authority": "none",
        "provider_accounting": accounting,
        "discovery_readiness": readiness,
        "research_plan_id": plan.plan_id,
        "ambiguity_objects": [row.model_dump(mode="json") for row in plan.ambiguities],
        "research_obligations": [row.model_dump(mode="json") for row in plan.obligations],
        "source_candidate_ids": [],
        "publisher_candidates": discovery["candidates"],
    }).model_dump(mode="json")
    result = {
        "schema_version": "shopping-case-research-v1",
        "case_id": case_id,
        "status": "publisher_resolution_required",
        "retained_purpose": plan.retained_purpose,
        "research_plan": plan.model_dump(mode="json"),
        "research_contract": contract,
        "research": discovery,
        "product_shelves": shelves,
        "ambiguity_exploration": exploration,
        "evidence_outcome": "unresolved",
        "research_delta": [],
        "cart_mutation": "not_authorized",
        "supplier_send": "not_authorized",
        "trace_id": case_id.removeprefix("sc-"),
    }
    from src.app.services.research_outcome import build_research_outcome

    result["research_outcome"] = build_research_outcome(
        case_id=case_id,
        case_revision=int(case.revision or 1),
        operation_id=str(discovery.get("run_id") or plan.plan_id),
        research=discovery,
        requirements={"accepted": [], "rejected": []},
        catalog_authority="blocked",
        commerce_authority="none",
    ).model_dump(mode="json")
    log_trace_event(
        trace_id=result["trace_id"],
        event_type="open_world_discovery_completed",
        source_type="stage",
        source_id="SearXNG_Discovery",
        target_type="shopping_case",
        target_id=case_id,
        payload={
            "case_id": case_id,
            "execution_status": discovery.get("status"),
            "cancellation": discovery.get("cancellation"),
            "publisher_status": "unresolved",
            "publisher_candidates": discovery["candidates"],
            "receipts": discovery["receipts"],
            "evidence_ladder": discovery.get("evidence_ladder") or [],
            "provider_accounting": accounting,
            "query_proposal": discovery.get("query_proposal"),
            "official_claims": [],
            "qualification_authority": "none",
            "cart_authority": "none",
        },
    )
    return result


def execute_open_world_publisher_discovery(
    db: Session,
    **kwargs: Any,
) -> dict[str, Any]:
    """Deprecated synchronous boundary retained for offline certification/tests."""

    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(execute_open_world_publisher_discovery_async(db, **kwargs))
    raise RuntimeError("sync_open_world_research_called_from_async_context")


__all__ = [
    "OpenWorldResearchUnavailable", "execute_open_world_publisher_discovery",
    "execute_open_world_publisher_discovery_async",
]
