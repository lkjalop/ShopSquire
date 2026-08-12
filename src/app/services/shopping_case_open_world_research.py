"""Case-bound orchestration for unresolved-publisher research.

This service deliberately stops after discovery and candidate persistence. Search
results are not requirements, and a discovered publisher has no qualification or
commerce authority until the separate approval/fetch/extraction path accepts it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
from src.app.services.open_world_research_discovery import discover_open_world_publishers
from src.app.services.open_world_query_proposal import propose_open_world_queries
from src.app.services.shopping_case_research_contract import (
    project_research_execution_contract,
)
from src.app.services.shopping_case_truth_projection import ShoppingCaseTruthProjection


@dataclass(frozen=True)
class OpenWorldResearchUnavailable(Exception):
    code: str
    readiness: dict[str, Any]


def _governed_domains() -> list[str]:
    return sorted({
        str(domain).strip().lower()
        for source in load_official_source_manifest().get("sources") or []
        if source.get("review_status") == "approved"
        for domain in source.get("allowed_domains") or []
        if str(domain).strip()
    })


def execute_open_world_publisher_discovery(
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
) -> dict[str, Any]:
    """Discover and persist publisher candidates for one durable shopping case."""

    if plan.publisher_status != "unresolved":
        raise ValueError("open_world_plan_required")
    readiness = external_search_readiness(
        allowlist=_governed_domains(),
        tenant_id=tenant_id,
        runtime_status=runtime_status,
    )
    if not readiness.get("effective"):
        raise OpenWorldResearchUnavailable(
            code=str(readiness.get("error_code") or "external_research_degraded"),
            readiness=readiness,
        )

    discovery_plan, query_proposal = propose_open_world_queries(plan)
    discovery = discover_open_world_publishers(
        discovery_plan,
        search_url_template=search_url_template,
    )
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
        "trace_id": case_id.removeprefix("sc-"),
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
    log_trace_event(
        trace_id=result["trace_id"],
        event_type="open_world_discovery_completed",
        source_type="stage",
        source_id="SearXNG_Discovery",
        target_type="shopping_case",
        target_id=case_id,
        payload={
            "case_id": case_id,
            "publisher_status": "unresolved",
            "publisher_candidates": discovery["candidates"],
            "receipts": discovery["receipts"],
            "provider_accounting": accounting,
            "query_proposal": discovery.get("query_proposal"),
            "official_claims": [],
            "qualification_authority": "none",
            "cart_authority": "none",
        },
    )
    return result


__all__ = ["OpenWorldResearchUnavailable", "execute_open_world_publisher_discovery"]
