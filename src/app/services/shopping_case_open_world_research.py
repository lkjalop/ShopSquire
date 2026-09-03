"""Case-bound orchestration for unresolved-publisher research.

This service deliberately stops after discovery and candidate persistence. Search
results are not requirements, and a discovered publisher has no qualification or
commerce authority until the separate approval/fetch/extraction path accepts it.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.case_publisher_candidate_workflow import (
    CASE_ALLOWED_CLAIM_TYPES,
    execute_case_candidate_research,
    persist_discovered_candidates,
)
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


def identity_only_workload_authorization(
    identity_resolution: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Project cited identity without pretending requirements were resolved."""

    resolution = dict(identity_resolution or {})
    identity = dict(resolution.get("identity") or {})
    canonical_title = str(identity.get("canonical_title") or "").strip()
    if resolution.get("status") != "resolved" or not canonical_title:
        return None
    return {
        "status": "blocked",
        "reason": "named_workload_requirements_unresolved",
        "next_permitted_action": "resolve_workload_requirements",
        "state_prevented": [
            "catalog_qualification", "buyer_commitment", "supplier_rfq",
        ],
        "evidence": [{
            "status": "identity_resolved_requirements_pending",
            "requested_name": canonical_title,
            "resolved_name": canonical_title,
            "canonical_title": canonical_title,
            "publisher": identity.get("publisher"),
            "publisher_domain": identity.get("publisher_domain"),
            "release_state": identity.get("release_state") or "unknown",
            "release_date": identity.get("release_date"),
            "nearest_equivalent": identity.get("nearest_equivalent"),
            "supporting_row_ids": list(identity.get("supporting_row_ids") or []),
            "identity_authority": resolution.get("authority"),
            "requirements_completeness": "identity_only",
            "compiled_requirements": [],
            "qualification_authority": "none",
        }],
    }


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


def official_origin_auto_fetch_eligible(
    *, identity_resolution: dict[str, Any], candidate: dict[str, Any], policy: dict[str, Any],
) -> bool:
    """Require model-cited identity, direct-origin evidence, and exact domain agreement."""

    identity = dict(identity_resolution.get("identity") or {})
    ownership = dict(candidate.get("publisher_ownership_evaluation") or {})
    proposed_domain = str(identity.get("publisher_domain") or "").lower().removeprefix("www.")
    candidate_domain = str(candidate.get("registrable_domain") or "").lower().removeprefix("www.")
    title_terms = set(re.findall(
        r"[a-z0-9]+", str(identity.get("canonical_title") or "").casefold()
    ))
    candidate_title_terms = set(re.findall(
        r"[a-z0-9]+", str(candidate.get("title") or "").casefold()
    ))
    title_agrees = bool(title_terms and title_terms.issubset(candidate_title_terms))
    cited_top_row = "candidate-1" in set(identity.get("supporting_row_ids") or [])
    # A model may correctly decline to name a publisher domain even though the
    # independently evaluated top row is a direct publisher origin. In that
    # case require both an exact title-token containment and an explicit cite
    # to the top row. A proposed domain, however, must match exactly.
    origin_agrees = (
        proposed_domain == candidate_domain
        if proposed_domain else title_agrees and cited_top_row
    )
    return bool(
        policy.get("authorized")
        and identity_resolution.get("status") == "resolved"
        and identity.get("canonical_title")
        and origin_agrees
        and ownership.get("status") == "plausible_direct_origin"
        and float(ownership.get("confidence") or 0) >= 0.75
    )


def _catalog_claims_from_structured_resolution(
    resolution: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Project registry-compiled provider predicates into the shared fit ledger."""

    claims: list[dict[str, Any]] = []
    for evidence in list((resolution or {}).get("evidence") or []):
        if not isinstance(evidence, dict) or str(evidence.get("status") or "") != "resolved":
            continue
        for compiled in list(evidence.get("compiled_requirements") or []):
            if not isinstance(compiled, dict) or not compiled.get("attribute_key"):
                continue
            claims.append({
                "claim_id": str(
                    (compiled.get("source_claim_ids") or [
                        f"{evidence.get('provider_id') or 'provider'}:"
                        f"{evidence.get('app_id') or evidence.get('source_record_id') or 'record'}:"
                        f"{compiled.get('attribute_key')}"
                    ])[0]
                )[:240],
                "attribute": compiled.get("attribute_key"),
                "operator": compiled.get("operator"),
                "value": compiled.get("value"),
                "unit": compiled.get("unit"),
                "requirement_class": compiled.get("requirement_class") or "minimum",
                "authority_status": "verified_official",
                "source_id": evidence.get("provider_id") or evidence.get("source"),
                "source_url": evidence.get("source_url"),
                "observed_at": evidence.get("retrieved_at"),
            })
    return claims


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
    workload_kind_hints: list[str] | None = None,
    cancellation_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Discover and persist publisher candidates for one durable shopping case."""

    pipeline_started = time.monotonic()
    stage_timings: dict[str, int] = {}

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
    case_revision = int(case.revision or 1)
    discovery_plan, query_proposal = await _consume_interpretation_with_bounded_wait(
        db,
        tenant_id=tenant_id,
        case_id=case_id,
        case_revision=case_revision,
        plan=plan,
    )
    # No SQL transaction may remain open while public-network discovery runs.
    # Everything required by the provider is now an immutable value object.
    rollback = getattr(db, "rollback", None)
    if callable(rollback):
        rollback()
    stage_started = time.monotonic()
    discovery = await open_world_research_discovery.discover_open_world_publishers_async(
        discovery_plan,
        search_url_template=search_url_template,
        cancellation_requested=cancellation_requested,
    )
    stage_timings["discovery_ms"] = round((time.monotonic() - stage_started) * 1000)
    # If deterministic discovery found no credible origin, consume a planner
    # that may have completed while those calls were in flight. Dispatch only
    # its first distinct query: total provider fan-out is capped at four.
    if not discovery.get("candidates") and not (discovery.get("cancellation") or {}).get("requested"):
        retry_plan, retry_proposal = await _consume_interpretation_with_bounded_wait(
            db,
            tenant_id=tenant_id,
            case_id=case_id,
            case_revision=case_revision,
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
            rollback = getattr(db, "rollback", None)
            if callable(rollback):
                rollback()
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
    identity_enabled = str(
        os.getenv("OPEN_WORLD_IDENTITY_RESOLVER_ENABLED") or ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if identity_enabled and discovery.get("candidates"):
        from src.app.services.open_world_identity_resolution import (
            resolve_open_world_identity,
        )

        stage_started = time.monotonic()
        discovery["identity_resolution"] = await asyncio.to_thread(
            resolve_open_world_identity,
            plan.retained_purpose,
            list(discovery.get("candidates") or []),
        )
        stage_timings["identity_resolution_ms"] = round(
            (time.monotonic() - stage_started) * 1000
        )
    else:
        discovery["identity_resolution"] = {
            "status": "not_attempted", "identity": None, "model_calls": 0,
            "failure_code": (
                "no_candidate_rows" if not discovery.get("candidates")
                else "identity_resolver_disabled"
            ),
            "authority": "none",
        }
    # Identity must precede structured acquisition.  The first core pass sees
    # only the buyer's raw phrase; after cited resolution, retry enrolled
    # providers exactly once with the canonical title and the router's typed
    # kind.  No application aliases or title-specific branches are involved.
    from src.app.services.recommendation_core.workload_grounding import (
        resolve_canonical_workload_identity,
    )

    stage_started = time.monotonic()
    discovery["structured_provider_resolution"] = await asyncio.to_thread(
        resolve_canonical_workload_identity,
        discovery.get("identity_resolution"),
        workload_kind_hints=list(workload_kind_hints or []),
        consent=True,
    )
    stage_timings["structured_provider_resolution_ms"] = round(
        (time.monotonic() - stage_started) * 1000
    )
    structured_resolution = dict(discovery["structured_provider_resolution"] or {})
    structured_resolved = structured_resolution.get("status") == "resolved"
    if any(
        bool(attempt.get("allow_live"))
        for item in structured_resolution.get("evidence") or []
        if isinstance(item, dict)
        for attempt in item.get("provider_attempts") or []
        if isinstance(attempt, dict)
    ):
        accounting = dict(discovery.get("provider_accounting") or {})
        accounting["external_calls"] = int(accounting.get("external_calls") or 0) + 1
        discovery["provider_accounting"] = accounting
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

    # Only the named demo policy may convert a model-cited direct origin into
    # the existing case-only fetch workflow. Buyer-submitted URLs never enter
    # this branch: the candidate URL came from governed discovery.
    from src.app.services.research_policy import resolved_origin_auto_fetch_policy

    auto_fetch_policy = resolved_origin_auto_fetch_policy(case_id=case_id)
    discovery["official_origin_auto_fetch_policy"] = auto_fetch_policy
    top_candidate = discovery["candidates"][0] if discovery.get("candidates") else None
    if structured_resolved:
        discovery["official_origin_auto_fetch"] = {
            "status": "not_needed_structured_provider_resolved",
            "failure_code": None,
        }
    elif top_candidate and official_origin_auto_fetch_eligible(
        identity_resolution=discovery["identity_resolution"],
        candidate=top_candidate,
        policy=auto_fetch_policy,
    ):
        candidate_row = persisted_by_url.get(str(top_candidate.get("url") or ""))
        if candidate_row is not None:
            stage_started = time.monotonic()
            auto_result, auto_error = await execute_case_candidate_research(
                db,
                candidate=candidate_row,
                case=case,
                tenant_id=tenant_id,
                uid=uid,
                expected_version=int(candidate_row.version),
                idempotency_key=(
                    f"policy:{auto_fetch_policy['profile_id']}:{case_id}:"
                    f"{candidate_row.candidate_id}"
                ),
                allowed_claim_types=sorted(CASE_ALLOWED_CLAIM_TYPES),
                approval_basis=str(auto_fetch_policy["policy_basis"]),
            )
            discovery["official_origin_auto_fetch"] = (
                auto_result if auto_result is not None else {
                    "status": "failed", "failure_code": auto_error,
                }
            )
            stage_timings["official_origin_fetch_and_extract_ms"] = round(
                (time.monotonic() - stage_started) * 1000
            )
    else:
        discovery["official_origin_auto_fetch"] = {
            "status": "not_authorized_or_identity_origin_mismatch",
            "failure_code": "explicit_case_approval_required",
        }

    stage_timings["total_ms"] = round((time.monotonic() - pipeline_started) * 1000)
    discovery["stage_timings"] = stage_timings

    structured_claims = _catalog_claims_from_structured_resolution(
        discovery.get("structured_provider_resolution")
    )
    shelves = project_accepted_catalog(
        db,
        accepted_claims=structured_claims,
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
        "status": (
            "requirements_resolved"
            if structured_claims
            else
            "claims_pending_review"
            if (discovery.get("official_origin_auto_fetch") or {}).get("claims")
            else "publisher_resolution_required"
        ),
        "retained_purpose": plan.retained_purpose,
        "research_plan": plan.model_dump(mode="json"),
        "research_contract": contract,
        "research": discovery,
        "product_shelves": shelves,
        "ambiguity_exploration": exploration,
        "evidence_outcome": (
            "verified_structured_requirements" if structured_claims else "unresolved"
        ),
        "research_delta": [],
        "cart_mutation": "not_authorized",
        "supplier_send": "not_authorized",
        "trace_id": case_id.removeprefix("sc-"),
    }
    identity_authorization = identity_only_workload_authorization(
        discovery.get("identity_resolution")
    )
    if structured_claims:
        result["workload_authorization"] = {
            "status": "resolved",
            "reason": "enrolled_structured_provider_requirements",
            "next_permitted_action": "catalog_qualification",
            "state_prevented": ["buyer_commitment", "supplier_rfq"],
            "evidence": list(structured_resolution.get("evidence") or []),
        }
        resolved_evidence = next((
            item for item in structured_resolution.get("evidence") or []
            if isinstance(item, dict) and item.get("status") == "resolved"
        ), {})
        title = str(
            resolved_evidence.get("canonical_title")
            or resolved_evidence.get("resolved_name")
            or "the requested workload"
        )
        release_state = str(resolved_evidence.get("release_state") or "unknown")
        release_date = str(resolved_evidence.get("release_date") or "").strip()
        release_text = release_state + (f" ({release_date})" if release_date else "")
        result["assistant_message"] = (
            f"I resolved {title} through an enrolled structured source. It is {release_text}, "
            "and its published minimum requirements were applied to the catalog. "
            "Recommendations remain non-transactional until you choose one."
        )
    elif identity_authorization is not None:
        result["workload_authorization"] = identity_authorization
    from src.app.services.research_outcome import build_research_outcome

    result["research_outcome"] = build_research_outcome(
        case_id=case_id,
        case_revision=case_revision,
        operation_id=str(discovery.get("run_id") or plan.plan_id),
        research=discovery,
        requirements={"accepted": structured_claims, "rejected": []},
        catalog_authority="permitted" if structured_claims else "blocked",
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
