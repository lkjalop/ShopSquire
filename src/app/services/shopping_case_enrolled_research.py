"""Case-bound execution for reviewed, enrolled official workload sources."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from sqlalchemy.orm import Session

from src.app.models.orm import ShoppingCase
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.awaitable_provider import await_provider_result
from src.app.services.case_research_plan import CaseResearchPlan, plan_hypothesis_labels
from src.app.services.commerce_feature_readiness import (
    external_search_readiness,
    record_external_research_runtime_observation,
)
from src.app.services.decision_log import log_trace_event
from src.app.services import official_workload_research
from src.app.services.research_explainability_projection import (
    project_research_explainability,
)
from src.app.services.shopping_case_research_contract import (
    project_research_execution_contract,
)
from src.app.services.shopping_case_truth_projection import ShoppingCaseTruthProjection


@dataclass(frozen=True)
class EnrolledResearchUnavailable(Exception):
    status_code: int
    detail: dict[str, Any]


def _validate_source_policies(
    sources: Sequence[dict[str, Any]], *, source_candidate_ids: list[str],
) -> None:
    if not sources:
        raise EnrolledResearchUnavailable(409, {
            "code": "publisher_policy_review_required",
            "message": "Applicable publisher sources exist, but none is approved for this tenant.",
            "source_candidate_ids": source_candidate_ids,
        })
    invalid = [
        str(source.get("source_id") or "unknown")
        for source in sources
        if (
            source.get("review_status") != "approved"
            or int(source.get("freshness_sla_hours") or 0) <= 0
            or (source.get("publisher_policy") or {}).get("direct_origin_required") is not True
        )
    ]
    if invalid:
        raise EnrolledResearchUnavailable(409, {
            "code": "publisher_policy_or_freshness_not_enrolled",
            "message": "Applicable sources lack an approved direct-origin policy or freshness SLA.",
            "source_ids": invalid,
        })


async def execute_enrolled_official_research(
    db: Session,
    *,
    plan: CaseResearchPlan,
    approved_sources: Sequence[dict[str, Any]],
    tenant_id: str,
    case_id: str,
    case: ShoppingCase,
    hypothesis_ids: list[str],
    candidate_configuration_ids: list[str],
    budget_cents: int | None,
    runtime_status: dict[str, Any],
    configured_search_url: str,
    consent_receipt: dict[str, Any],
    cancellation_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Fetch, compile, reconcile and rerank one enrolled-source case.

    The returned prose and shelves are projections of typed claims. Discovery
    snippets and model text never become product-fit or commerce authority.
    """

    if plan.publisher_status != "resolved_enrolled":
        raise ValueError("enrolled_research_plan_required")
    if consent_receipt.get("authorized") is not True:
        raise EnrolledResearchUnavailable(403, {
            "code": "research_consent_receipt_required",
            "message": "No research call was dispatched because explicit consent is missing.",
        })
    sources = [dict(source) for source in approved_sources]
    _validate_source_policies(sources, source_candidate_ids=list(plan.source_candidate_ids))
    source_domains = sorted({
        str(domain).strip().lower()
        for source in sources
        for domain in source.get("allowed_domains") or []
        if str(domain).strip()
    })
    readiness = external_search_readiness(
        allowlist=source_domains,
        tenant_id=tenant_id,
        runtime_status=runtime_status,
    )
    canonical_direct_ready = all(bool(source.get("canonical_entrypoints")) for source in sources)
    hard_errors = {
        "external_research_disabled",
        "external_research_tenant_not_enrolled",
        "discovery_domain_allowlist_not_configured",
    }
    if not readiness["effective"] and (
        readiness.get("error_code") in hard_errors or not canonical_direct_ready
    ):
        code = str(readiness.get("error_code") or "external_research_degraded")
        messages = {
            "external_research_disabled": "Approved-source research is disabled by operator policy.",
            "discovery_endpoint_not_configured": (
                "The discovery endpoint is not configured. Upload requirements or ask an operator "
                "to enroll a SearXNG-compatible endpoint."
            ),
            "discovery_endpoint_unreachable": "The configured discovery endpoint was observed as unreachable.",
            "discovery_endpoint_degraded": "The configured discovery endpoint is degraded; no research call was dispatched.",
            "discovery_reachability_not_observed": "Discovery is configured but has no successful reachability observation.",
            "external_research_tenant_not_enrolled": "This tenant is not enrolled for approved-source research.",
        }
        raise EnrolledResearchUnavailable(
            403 if code == "external_research_tenant_not_enrolled" else 503,
            {
                "code": code,
                "message": messages.get(code, readiness.get("reason") or "Research is unavailable."),
                "readiness": {
                    key: readiness.get(key) for key in (
                        "configured", "reachable", "effective", "degraded",
                        "capability_status", "last_success_at", "last_failure_at",
                        "last_failure_code",
                    )
                },
            },
        )
    search_url = configured_search_url if readiness["effective"] else ""
    before = project_accepted_catalog(
        db,
        accepted_claims=[],
        desired_outcome=plan.retained_purpose,
        budget_cents=budget_cents,
        tenant_id=tenant_id,
        candidate_configuration_ids=candidate_configuration_ids,
    ).model_dump(mode="json")
    research = await await_provider_result(official_workload_research.research_official_sources(
        plan.retained_purpose,
        search_url_template=search_url,
        sources=sources,
        plan_id=plan.plan_id,
        hypothesis_ids=hypothesis_ids,
        tenant_id=tenant_id,
        evidence_cache=official_workload_research.DEFAULT_OFFICIAL_EVIDENCE_CACHE,
        cancellation_requested=cancellation_requested,
    ))
    research["discovery_readiness"] = {
        key: readiness.get(key) for key in (
            "configured", "reachable", "effective", "degraded", "capability_status",
            "error_code", "last_discovery_success_at", "last_discovery_result_count",
        )
    }
    research["canonical_direct_ready"] = canonical_direct_ready
    record_external_research_runtime_observation(research)
    from src.app.services.evidence_synthesis_ledger import (
        build_evidence_synthesis_ledger,
    )

    synthesis = build_evidence_synthesis_ledger(
        case_id=case_id,
        case_revision=int(case.revision or 1),
        query=plan.retained_purpose,
        purpose=plan.retained_purpose,
        consent_receipt=consent_receipt,
        research=research,
        approved_sources=sources,
        candidate_configuration_ids=candidate_configuration_ids,
    )
    research["evidence_synthesis_ledger"] = synthesis.model_dump(mode="json")
    # Only a provider-observed run may let the new ledger narrow executable
    # claims. Historical unit fixtures predate source-execution receipts; keep
    # their compatibility projection while the ledger correctly labels their
    # trust status as unresolved/rejected. Live and cache-backed runs always
    # carry source execution rows from ``official_workload_research``.
    if research.get("source_execution"):
        accepted_claim_ids = {
            row.claim_id for row in synthesis.claims if row.status == "accepted"
        }
        research["claims"] = [
            claim for claim in research["claims"]
            if str(claim.get("claim_id") or "") in accepted_claim_ids
        ]
    after = project_accepted_catalog(
        db,
        accepted_claims=research["claims"],
        desired_outcome=plan.retained_purpose,
        budget_cents=budget_cents,
        tenant_id=tenant_id,
        candidate_configuration_ids=candidate_configuration_ids,
        hypothesis_labels=plan_hypothesis_labels(plan),
        hypothesis_claims={
            hypothesis.hypothesis_id: [
                claim for claim in research["claims"]
                if str(claim.get("source_id") or "") in set(hypothesis.source_ids)
            ]
            for hypothesis in plan.hypotheses
        },
    ).model_dump(mode="json")
    delta = official_workload_research.ranking_delta(before, after)
    outcome = str(research.get("evidence_outcome") or (
        "product_requirements" if research["claims"]
        else "context_only" if research["context_claims"]
        else "unresolved"
    ))
    was_cancelled = research.get("status") == "cancelled"
    # Cancellation is execution state, not evidence state.  Keep the canonical
    # evidence vocabulary valid while preserving the cancellation in
    # ``execution`` and the outer response status.
    status = (
        "unresolved" if was_cancelled
        else "researched" if outcome == "product_requirements"
        else "context_only" if outcome == "context_only"
        # Parser/reviewer workflow states such as
        # ``claims_pending_policy_review`` are execution detail, not values in
        # the buyer-facing canonical evidence vocabulary.
        else "unresolved"
    )
    contract = project_research_execution_contract(
        plan, requirements_compiled=outcome == "product_requirements",
    ).model_dump(mode="json")
    research.update({"research_plan_id": plan.plan_id, "execution_contract": contract})
    after.update({
        "evidence_status": status,
        "research_delta": delta,
        "official_claim_count": len(research["claims"]),
        "context_claim_count": len(research["context_claims"]),
    })
    receipt, narration = project_research_explainability(
        purpose=plan.retained_purpose, research=research, shelves=after, delta=delta,
    )
    after.update({
        "research_receipt": receipt.model_dump(mode="json"),
        "narration_projection": narration.model_dump(mode="json"),
    })
    mode = str(research.get("execution_mode") or "").strip().lower()
    accounting = research.get("provider_accounting") or {}
    if was_cancelled:
        execution = "official_research_cancelled"
    elif mode == "evidence_cache" or (
        int(accounting.get("cache_hits") or 0) > 0
        and int(accounting.get("external_calls") or 0) == 0
    ):
        execution = "governed_evidence_cache_hit"
    elif mode == "live_network" or int(accounting.get("external_calls") or 0) > 0:
        execution = "live_official_research_completed"
    elif mode == "not_executed":
        execution = "official_research_not_executed"
    else:
        execution = "governed_official_research_completed"
    exploration = ShoppingCaseTruthProjection.model_validate({
        "schema_version": "ambiguity-exploration-v1",
        "case_id": case_id,
        "trace_id": case_id.removeprefix("sc-"),
        "retained_purpose": plan.retained_purpose,
        "status": status,
        "interpretations": [row.model_dump(mode="json") for row in plan.hypotheses],
        "next_question": {"id": "research_scope", "text": plan.next_question},
        "execution": execution,
        "evidence": (
            "scoped_product_requirements_compiled" if outcome == "product_requirements"
            else "authoritative_context_only" if outcome == "context_only"
            else "no_accepted_claims"
        ),
        "decision": "conditional_fit_allowed" if outcome == "product_requirements" else "provisional_exploration_only",
        "cart_authority": "none",
        "provider_accounting": research["provider_accounting"],
        "discovery_readiness": research["discovery_readiness"],
        "research_plan_id": plan.plan_id,
        "ambiguity_objects": [row.model_dump(mode="json") for row in plan.ambiguities],
        "research_obligations": [
            {
                **row.model_dump(mode="json"),
                "status": (
                    "resolved" if row.obligation_id == "official_requirements"
                    else "blocked" if row.obligation_id == "exact_product_identity"
                    and outcome != "product_requirements"
                    else row.status
                ),
            }
            for row in plan.obligations
        ],
        "source_candidate_ids": list(plan.source_candidate_ids),
    }).model_dump(mode="json")
    result = {
        "schema_version": "shopping-case-research-v1",
        "case_id": case_id,
        "status": "research_cancelled" if was_cancelled else "research_completed",
        "retained_purpose": plan.retained_purpose,
        "research_plan": plan.model_dump(mode="json"),
        "research_contract": contract,
        "research": research,
        "product_shelves": after,
        "ambiguity_exploration": exploration,
        "evidence_outcome": outcome,
        "research_delta": delta,
        "decision_trace": {
            "research_trust": synthesis.decision_trace_projection,
            "evidence_synthesis_ledger_id": synthesis.ledger_id,
        },
        "cart_mutation": "not_authorized",
        "supplier_send": "not_authorized",
        "trace_id": case_id.removeprefix("sc-"),
        "canonical_truth": exploration["canonical_truth"],
    }
    case.retained_purpose = plan.retained_purpose
    case.updated_at = datetime.now(timezone.utc)
    from src.app.services.shopping_case_decision_persistence import (
        persist_requirement_acceptance_decision,
    )

    result["procurement_decision_run"] = persist_requirement_acceptance_decision(
        db,
        tenant_id=tenant_id,
        case_id=case_id,
        case_revision=int(case.revision or 1),
        retained_purpose=plan.retained_purpose,
        proposal_id=plan.plan_id,
        proposal_version=int(case.revision or 1),
        accepted_claims=[dict(row) for row in research.get("claims") or []],
        product_shelves=after,
        corroboration=result,
        qualification_authority=(
            "requirements" if outcome == "product_requirements" else "none"
        ),
        observed_at=case.updated_at,
        idempotency_key=f"research:{plan.plan_id}:case-revision:{int(case.revision or 1)}",
    )
    db.commit()
    log_trace_event(
        trace_id=result["trace_id"],
        event_type="official_research_rerank_completed",
        source_type="stage",
        source_id="Governed_Official_Research",
        target_type="shopping_case",
        target_id=case_id,
        payload={
            "case_id": case_id,
            "status": result["status"],
            "provider_accounting": research["provider_accounting"],
            "receipts": research["receipts"],
            "research_delta": delta,
            "evidence_ladder": research.get("evidence_ladder", []),
            "source_execution": research.get("source_execution", []),
            "official_claims": research["claims"],
            "context_claims": research["context_claims"],
            "evidence_outcome": outcome,
            "canonical_truth": exploration["canonical_truth"],
            "cart_authority": "none",
            "supplier_authority": "none",
        },
    )
    return result


__all__ = ["EnrolledResearchUnavailable", "execute_enrolled_official_research"]
