"""Case-scoped buyer requirement review and acceptance API."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from src.app.models.db import get_db
from src.app.models.orm import (
    RequirementProposal,
    ShoppingCase,
    ShoppingCasePublisherCandidate,
)
from src.app.services.buyer_requirement_evidence import (
    ExtractedRequirementClaim,
    extract_buyer_requirement_claims,
)
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.infrastructure_alternative_projection import project_infrastructure_alternatives
from src.app.services.evidence_acquisition_ladder import choose_evidence_stage
from src.app.services.fulfillment_choice_reducer import reduce_fulfillment_choices
from src.app.services.decision_log import log_trace_event
from src.app.services.commerce_feature_readiness import (
    external_research_runtime_observation,
    external_search_readiness,
    record_external_research_runtime_observation,
)
from src.app.services.requirement_claim_reconciliation import reconcile_requirement_claims


router = APIRouter(prefix="/api/v1/shopping-cases", tags=["shopping-cases"])


class CreateRequirementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    retained_purpose: str | None = Field(default=None, max_length=500)
    source_reference: str = Field(min_length=1, max_length=500)
    claims: list[ExtractedRequirementClaim] = Field(min_length=1, max_length=64)


class CreateManualRequirementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    retained_purpose: str | None = Field(default=None, max_length=500)
    text: str = Field(min_length=3, max_length=10_000)


class ClaimCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str = Field(min_length=1, max_length=240)
    attribute: str = Field(min_length=1, max_length=80)
    operator: str = Field(min_length=1, max_length=24)
    value: int | float | str | list[str]
    unit: str | None = Field(default=None, max_length=40)
    requirement_class: Literal["minimum", "recommended", "target", "optimal"]
    constraint_tier: Literal["preferred", "acceptable_alternative"] = "preferred"
    condition: str | None = Field(default=None, max_length=500)


class AcceptRequirementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    expected_proposal_version: int = Field(ge=1)
    accepted_claim_ids: list[str] = Field(default_factory=list, max_length=64)
    rejected_claim_ids: list[str] = Field(default_factory=list, max_length=64)
    corrections: list[ClaimCorrection] = Field(default_factory=list, max_length=64)
    research_choice: Literal["local_only", "research_and_corroborate"]


class FulfillmentOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    requested_quantity: int = Field(ge=1, le=1_000_000)
    available_now: int = Field(ge=0, le=1_000_000)
    known_lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    deadline_days: int | None = Field(default=None, ge=0, le=3650)
    has_next_best: bool = False
    has_architecture_alternative: bool = False


class ResearchShoppingCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    budget_cents: int | None = Field(default=None, ge=1, le=1_000_000_000)
    research_plan_id: str = Field(pattern=r"^crp-[a-f0-9]{20}$")
    ambiguity_object_ids: list[str] = Field(min_length=1, max_length=8)
    hypothesis_ids: list[str] = Field(min_length=1, max_length=3)
    research_authorized: Literal[True]
    refresh_authorized: bool = False


class ApprovePublisherCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    expected_candidate_version: int = Field(ge=1)
    approval_scope: Literal["case_only"] = "case_only"
    allowed_claim_types: list[Literal[
        "minimum_requirements", "recommended_requirements", "target_requirements",
        "compatibility", "operating_system_support", "hardware_certification",
    ]] = Field(
        default_factory=lambda: [
            "minimum_requirements", "recommended_requirements", "compatibility",
        ],
        min_length=1,
        max_length=6,
    )
    research_authorized: Literal[True]


class ResolveBuyerEvidenceSourceRequest(BaseModel):
    """Resolve one buyer-supplied official source hint inside an active case."""

    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    source_url: str | None = Field(default=None, min_length=8, max_length=2000)
    vendor_name: str | None = Field(default=None, min_length=2, max_length=200)
    research_authorized: bool = False
    refresh_authorized: bool = False


class CreateCaseInterpretationRequest(BaseModel):
    """Buyer-authored outcome only; the server owns all research scope."""

    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    retained_purpose: str = Field(min_length=3, max_length=500)
    storefront_taxonomy_handle: str | None = Field(default=None, min_length=2, max_length=160)


class ProposeCaseCartMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=500)


class SelectFulfillmentContinuationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=0)
    choice: Literal[
        "split_delivery", "wait_preferred", "next_best_now", "supplier_enquiry", "substitute",
    ]
    preferred_sku: str = Field(min_length=1, max_length=120)
    substitute_sku: str | None = Field(default=None, min_length=1, max_length=120)
    requested_quantity: int = Field(ge=1, le=500)
    available_now: int = Field(ge=0, le=500)
    deadline_days: int | None = Field(default=None, ge=0, le=3650)


class ConfirmFulfillmentCartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)
    selected_offer_id: str | None = Field(default=None, max_length=120)
    substitution_authorized: bool = False


class PortfolioNarrationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    projection: dict[str, Any]


def _tenant(value: str | None) -> str:
    return str(value or "default").strip() or "default"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/{case_id}/narration-preview")
def portfolio_narration_preview(
    case_id: str,
    body: PortfolioNarrationPreviewRequest,
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Buyer-triggered prose preview; ranking and commerce authority remain deterministic."""
    from src.app.services.portfolio_narration_preview import (
        ShelfNarrationProjection, render_portfolio_narration_preview,
    )

    tenant_id = _tenant(x_tenant_id)
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="shopping_case_not_found")
    if case.uid != body.uid:
        raise HTTPException(status_code=403, detail="shopping_case_not_owned")
    projection = ShelfNarrationProjection.model_validate(body.projection)
    result = render_portfolio_narration_preview(projection)
    result.update({
        "schema_version": "portfolio-narration-preview-response-v1",
        "case_id": case_id, "cart_authority": "none", "supplier_authority": "none",
    })
    return result


def _external_research_runtime_status() -> dict[str, Any]:
    """Read the latest probe observation without performing network I/O.

    Deployments may project their health-probe observations into these values.
    The explicit local proof enrollment is handled separately by readiness and
    never appears here as a successful observation.
    """

    status = str(os.getenv("EXTERNAL_RESEARCH_RUNTIME_STATUS") or "").strip().lower()
    reachable: bool | None = None
    if status in {"healthy", "reachable", "effective", "degraded"}:
        reachable = True
    elif status in {"unreachable", "failed"}:
        reachable = False
    observed = external_research_runtime_observation()
    configured = {
        "status": status or None,
        "reachable": reachable,
        "degraded": (status == "degraded") if status else None,
        "last_success_at": os.getenv("EXTERNAL_RESEARCH_LAST_SUCCESS_AT"),
        "last_failure_at": os.getenv("EXTERNAL_RESEARCH_LAST_FAILURE_AT"),
        "last_failure_code": os.getenv("EXTERNAL_RESEARCH_LAST_FAILURE_CODE"),
    }
    observed.update({key: value for key, value in configured.items() if value is not None})
    return observed


def _trace_id(proposal_id: str, version: int) -> str:
    return "req-" + hashlib.sha256(f"{proposal_id}:{version}".encode()).hexdigest()[:20]


def _buyer_claim_reconciliation(
    buyer_claims: list[dict[str, Any]], official_claims: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = [
        row.model_dump(mode="json")
        for row in reconcile_requirement_claims(buyer_claims, official_claims)
    ]
    counts = {
        status: sum(row["status"] == status for row in rows)
        for status in ("corroborated", "contradicted", "unresolved", "preference_only")
    }
    return rows, counts


def _payload_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _case_research_plan_from_trace(
    db, *, case_id: str, tenant_id: str,
):
    """Rebuild a plan only from the server-recorded ambiguity event."""

    from src.app.services.case_research_plan import build_case_research_plan
    from src.app.services.decision_log import get_cached_trace_events

    trace_id = case_id.removeprefix("sc-")
    events = list(get_cached_trace_events(trace_id))
    if not events:
        try:
            rows = db.execute(text(
                "SELECT event_type, payload FROM decision_trace_events "
                "WHERE trace_id=:trace_id AND tenant_id=:tenant_id ORDER BY created_at ASC"
            ), {"trace_id": trace_id, "tenant_id": tenant_id}).mappings().all()
            events = [dict(row) for row in rows]
        except Exception:
            events = []
    for event in reversed(events):
        if str(event.get("event_type") or "") != "ambiguity_exploration_projected":
            continue
        payload = _payload_object(event.get("payload"))
        purpose = str(payload.get("retained_purpose") or "").strip()
        recorded_plan_id = str(payload.get("research_plan_id") or "").strip()
        plan = build_case_research_plan(purpose) if purpose else None
        if plan is None and purpose and recorded_plan_id:
            plan = build_case_research_plan(purpose, allow_open_world=True)
        if plan is None or plan.plan_id != recorded_plan_id:
            return None
        return plan
    return None


def _case_catalog_candidate_set_from_trace(
    db, *, case_id: str, tenant_id: str,
):
    """Load the immutable catalog boundary recorded with the shopping case."""

    from src.app.services.case_catalog_candidates import CatalogCandidateSet
    from src.app.services.decision_log import get_cached_trace_events

    trace_id = case_id.removeprefix("sc-")
    events = list(get_cached_trace_events(trace_id))
    if not events:
        try:
            rows = db.execute(text(
                "SELECT event_type, payload FROM decision_trace_events "
                "WHERE trace_id=:trace_id AND tenant_id=:tenant_id ORDER BY created_at ASC"
            ), {"trace_id": trace_id, "tenant_id": tenant_id}).mappings().all()
            events = [dict(row) for row in rows]
        except Exception:
            events = []
    for event in reversed(events):
        if str(event.get("event_type") or "") != "ambiguity_exploration_projected":
            continue
        raw = _payload_object(event.get("payload")).get("catalog_candidate_set")
        if isinstance(raw, dict):
            try:
                return CatalogCandidateSet.model_validate(raw)
            except ValueError:
                break
    # A legacy/malformed case may continue gathering evidence, but cannot fall
    # back to the tenant-wide catalog and present that as a query-specific shelf.
    return CatalogCandidateSet(
        retained_purpose="Unresolved legacy shopping case",
        status="unresolved",
        taxonomy_source="unresolved",
        reason="case_candidate_set_not_recorded",
    )


def _case_trace_has_event(db, *, case_id: str, tenant_id: str, event_type: str) -> bool:
    from src.app.services.decision_log import get_cached_trace_events

    trace_id = case_id.removeprefix("sc-")
    if any(str(row.get("event_type") or "") == event_type for row in get_cached_trace_events(trace_id)):
        return True
    try:
        return db.execute(text(
            "SELECT 1 FROM decision_trace_events "
            "WHERE trace_id=:trace_id AND tenant_id=:tenant_id AND event_type=:event_type LIMIT 1"
        ), {
            "trace_id": trace_id, "tenant_id": tenant_id, "event_type": event_type,
        }).first() is not None
    except Exception:
        return False


@router.post("/interpretations")
def create_case_interpretation(
    body: CreateCaseInterpretationRequest,
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Create the zero-network provisional case before any narration provider runs.

    An empty match is a normal local-persona outcome, represented by 204 so the
    existing chat route remains authoritative for covered catalogue requests.
    """

    from fastapi import Response

    from src.app.services.case_research_plan import (
        build_case_research_plan, plan_hypothesis_labels,
    )

    tenant_id = _tenant(x_tenant_id)
    from src.app.services.case_catalog_candidates import build_case_catalog_candidate_set

    candidate_set = build_case_catalog_candidate_set(
        db,
        retained_purpose=body.retained_purpose,
        tenant_id=tenant_id,
        storefront_taxonomy_handle=body.storefront_taxonomy_handle,
    )
    if candidate_set.reason == "buyer_named_category_outside_storefront_context":
        empty_projection = project_accepted_catalog(
            db, accepted_claims=[], desired_outcome=body.retained_purpose,
            tenant_id=tenant_id, candidate_configuration_ids=[],
        )
        return {
            "schema_version": "catalog-boundary-v1",
            "catalog_boundary": candidate_set.model_dump(mode="json"),
            "product_shelves": empty_projection.model_dump(mode="json"),
            "assistant_message": (
                f"That request is for {candidate_set.taxonomy_label or 'a different product category'}, "
                "which is outside this storefront's current catalog. I have not shown laptops or "
                "started workload research for it."
            ),
            "provider_accounting": {"external_calls": 0, "paid_calls": 0},
            "cart_mutation": "not_authorized",
            "supplier_send": "not_authorized",
        }

    plan = build_case_research_plan(body.retained_purpose)
    if plan is None:
        # Positive-evidence constraints such as vendor certification or an OS
        # support matrix cannot be satisfied by category similarity. This is a
        # generic evidence-gap trigger, not a workload/persona keyword branch.
        from src.app.services.recommendation_core.post_catalog_adjudicator import (
            explicit_evidence_constraints,
            suitability_evidence_requested,
        )

        if (
            explicit_evidence_constraints(body.retained_purpose)
            or suitability_evidence_requested(body.retained_purpose)
        ):
            plan = build_case_research_plan(body.retained_purpose, allow_open_world=True)
    if plan is None:
        return Response(status_code=204)

    trace_id = "case-" + uuid.uuid4().hex[:20]
    case_id = f"sc-{trace_id}"
    case = ShoppingCase(
        case_id=case_id, tenant_id=tenant_id, uid=body.uid, status="active",
        retained_purpose=plan.retained_purpose, created_at=_now(), updated_at=_now(),
    )
    db.add(case)
    db.commit()

    projection = project_accepted_catalog(
        db, accepted_claims=[], desired_outcome=plan.retained_purpose,
        tenant_id=tenant_id, hypothesis_labels=plan_hypothesis_labels(plan),
        candidate_configuration_ids=candidate_set.configuration_ids,
    )
    from src.app.services.shopping_case_truth_projection import ShoppingCaseTruthProjection

    exploration = ShoppingCaseTruthProjection.model_validate({
        "schema_version": "ambiguity-exploration-v1",
        "case_id": case_id,
        "trace_id": trace_id,
        "retained_purpose": plan.retained_purpose,
        "status": "provisional",
        "interpretations": [row.model_dump(mode="json") for row in plan.hypotheses],
        "next_question": {"id": "research_scope", "text": plan.next_question},
        "research_choices": [
            "research_approved_sources", "upload_requirements",
            "enter_specifications", "continue_provisionally",
        ],
        "execution": "local_exploration_completed",
        "evidence": "material_gaps",
        "decision": "exploration_allowed",
        "cart_authority": "none",
        "provider_accounting": {"external_calls": 0, "paid_calls": 0},
        "research_plan_id": plan.plan_id,
        "ambiguity_objects": [row.model_dump(mode="json") for row in plan.ambiguities],
        "research_obligations": [row.model_dump(mode="json") for row in plan.obligations],
        "source_candidate_ids": list(plan.source_candidate_ids),
    }).model_dump(mode="json")
    log_trace_event(
        trace_id=trace_id,
        event_type="ambiguity_exploration_projected",
        source_type="stage",
        source_id="Case_Bound_Interpretation",
        target_type="ui",
        target_id="research_fit_panel",
        payload={
            **exploration,
            "shelf_ids": [shelf.shelf_id for shelf in projection.shelves],
            "qualification_authority": "none",
            "commercial_authority": "none",
            "catalog_candidate_set": candidate_set.model_dump(mode="json"),
        },
    )
    return {
        "schema_version": "case-interpretation-v1",
        "case_id": case_id,
        "trace_id": trace_id,
        "ambiguity_exploration": exploration,
        "product_shelves": projection.model_dump(mode="json"),
        "catalog_candidate_set": candidate_set.model_dump(mode="json"),
        "assistant_message": (
            "I created a provisional shopping case from your outcome. The shelves are local "
            "catalog exploration, not verified fit. Answer the one material question or authorize "
            "approved-source research to corroborate the requirements."
        ),
        "provider_accounting": {"external_calls": 0, "paid_calls": 0},
        "cart_mutation": "not_authorized",
        "supplier_send": "not_authorized",
    }


@router.post("/{case_id}/requirement-proposals", status_code=201)
def create_requirement_proposal(
    case_id: str,
    body: CreateRequirementProposal,
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant(x_tenant_id)
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is not None and case.uid != body.uid:
        raise HTTPException(status_code=403, detail="shopping_case_not_owned")
    if case is None:
        case = ShoppingCase(
            case_id=case_id, tenant_id=tenant_id, uid=body.uid, status="active",
            retained_purpose=body.retained_purpose, created_at=_now(), updated_at=_now(),
        )
        db.add(case)
    proposal_id = "rp-" + uuid.uuid4().hex
    proposal = RequirementProposal(
        proposal_id=proposal_id, case_id=case_id, tenant_id=tenant_id, uid=body.uid,
        version=1, status="pending_review", source_reference=body.source_reference,
        claims_json=[claim.model_dump(mode="json") for claim in body.claims],
        created_at=_now(), updated_at=_now(),
    )
    db.add(proposal)
    db.commit()
    return {
        "case_id": case_id, "proposal_id": proposal_id, "proposal_version": 1,
        "status": "pending_review", "claims": proposal.claims_json,
        "cart_mutation": "not_authorized",
    }


@router.post("/{case_id}/requirement-proposals/from-text", status_code=201)
def create_manual_requirement_proposal(
    case_id: str,
    body: CreateManualRequirementProposal,
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Turn explicit buyer-entered specifications into the normal review contract."""

    source_reference = f"manual-specifications:{case_id}"
    claims = extract_buyer_requirement_claims(
        body.text,
        source_reference=source_reference,
        extraction_confidence=1.0,
    )
    if not claims:
        raise HTTPException(status_code=422, detail={
            "code": "no_explicit_requirement_claims",
            "message": (
                "No explicit supported specifications were found. Include values such as "
                "RAM 32GB, storage 1TB NVMe, 8 CPU cores, or Windows 11 Pro."
            ),
        })
    return create_requirement_proposal(
        case_id,
        CreateRequirementProposal(
            uid=body.uid,
            retained_purpose=body.retained_purpose,
            source_reference=source_reference,
            claims=claims,
        ),
        x_tenant_id=x_tenant_id,
        db=db,
    )


@router.post("/{case_id}/requirement-proposals/{proposal_id}/accept")
def accept_requirement_proposal(
    case_id: str,
    proposal_id: str,
    body: AcceptRequirementProposal,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant(x_tenant_id)
    proposal = db.execute(select(RequirementProposal).where(
        RequirementProposal.tenant_id == tenant_id,
        RequirementProposal.case_id == case_id,
        RequirementProposal.proposal_id == proposal_id,
    )).scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="requirement_proposal_not_found")
    if proposal.uid != body.uid:
        raise HTTPException(status_code=403, detail="requirement_proposal_not_owned")
    if proposal.acceptance_idempotency_key == idempotency_key and proposal.acceptance_json:
        return proposal.acceptance_json
    if proposal.acceptance_idempotency_key and proposal.acceptance_idempotency_key != idempotency_key:
        raise HTTPException(status_code=409, detail="requirement_proposal_already_accepted")
    if proposal.version != body.expected_proposal_version:
        raise HTTPException(status_code=409, detail={
            "code": "stale_requirement_proposal",
            "current_version": proposal.version,
        })

    source_by_id = {str(item.get("claim_id")): dict(item) for item in proposal.claims_json}
    accepted_ids = list(dict.fromkeys(body.accepted_claim_ids))
    rejected_ids = set(body.rejected_claim_ids)
    if set(accepted_ids) & rejected_ids:
        raise HTTPException(status_code=422, detail="claim_cannot_be_accepted_and_rejected")
    unknown = (set(accepted_ids) | rejected_ids | {row.claim_id for row in body.corrections}) - set(source_by_id)
    if unknown:
        raise HTTPException(status_code=422, detail={"unknown_claim_ids": sorted(unknown)})

    accepted: list[dict[str, Any]] = []
    corrections = {row.claim_id: row for row in body.corrections}
    for claim_id in accepted_ids:
        if claim_id in rejected_ids:
            continue
        item = source_by_id[claim_id]
        correction = corrections.get(claim_id)
        if correction is not None:
            item.update(correction.model_dump(exclude={"claim_id"}))
            item["buyer_corrected"] = True
        case_origin_evidence = (
            item.get("evidence_class") == "official_case_source"
            and item.get("approval_scope") == "case_only"
            and item.get("authority_status") == "verified_case_origin"
        )
        if correction is not None:
            # A buyer edit is useful evidence, but it is no longer the quoted
            # publisher claim and must return to provisional authority.
            case_origin_evidence = False
        item["acceptance_status"] = (
            "accepted_case_origin" if case_origin_evidence else "accepted_provisional"
        )
        item["authority_status"] = (
            "verified_case_origin" if case_origin_evidence else "unverified"
        )
        accepted.append(item)
    accepted_case_origin = any(
        item.get("authority_status") == "verified_case_origin" for item in accepted
    )
    result = {
        "schema_version": "requirement-acceptance-v1",
        "case_id": case_id,
        "proposal_id": proposal_id,
        "proposal_version": proposal.version + 1,
        "status": "accepted_case_evidence" if accepted_case_origin else "accepted_provisional",
        "accepted_claims": accepted,
        "rejected_claim_ids": sorted(rejected_ids),
        "research_choice": body.research_choice,
        "research_authorized": body.research_choice == "research_and_corroborate",
        "qualification_authority": "requirements" if accepted_case_origin else "none",
        "cart_mutation": "not_authorized",
        "trace_id": case_id.removeprefix("sc-"),
        "provider_accounting": {"external_calls": 0, "paid_calls": 0},
    }
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one()
    shelves = project_accepted_catalog(
        db, accepted_claims=accepted,
        desired_outcome=case.retained_purpose or "Buyer accepted requirements",
        tenant_id=tenant_id,
        candidate_configuration_ids=_case_catalog_candidate_set_from_trace(
            db, case_id=case_id, tenant_id=tenant_id,
        ).configuration_ids,
    )
    result["product_shelves"] = shelves.model_dump(mode="json")
    result["architecture_alternatives"] = project_infrastructure_alternatives(
        desired_outcome=case.retained_purpose or "Buyer accepted requirements",
        unresolved_inputs=["execution location", "mobility", "sustained performance"],
    ).model_dump(mode="json")
    result["evidence_acquisition"] = choose_evidence_stage(
        corpus_hit=False, cache_hit=False, accepted_buyer_upload=bool(accepted),
        ambiguous_material_gap=True,
        external_authorized=body.research_choice == "research_and_corroborate",
        local_discovery_enrolled=bool(os.getenv("EXTERNAL_RESEARCH_SEARCH_URL")),
        authoritative_origin_enrolled=bool(os.getenv("OFFICIAL_REQUIREMENTS_API_URL")),
        paid_discovery_allowed=False,
    ).model_dump(mode="json")
    if body.research_choice == "research_and_corroborate":
        plan = _case_research_plan_from_trace(db, case_id=case_id, tenant_id=tenant_id)
        if plan is None:
            result["corroboration"] = {
                "status": "blocked", "reason": "case_research_plan_not_found",
                "message": "The accepted claims remain provisional because this case has no governed research plan.",
            }
        elif not str(os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or "").strip():
            result["corroboration"] = {
                "status": "blocked", "reason": "local_discovery_not_enrolled",
                "message": "The accepted claims remain provisional because local discovery is not enrolled.",
            }
        else:
            try:
                corroboration = research_shopping_case(
                    case_id,
                    ResearchShoppingCaseRequest(
                        uid=body.uid, research_plan_id=plan.plan_id,
                        ambiguity_object_ids=[row.ambiguity_id for row in plan.ambiguities],
                        hypothesis_ids=[row.hypothesis_id for row in plan.hypotheses],
                        # The buyer explicitly asked to corroborate newly accepted
                        # evidence, so this is an authorized refresh of the same case.
                        research_authorized=True, refresh_authorized=True,
                    ),
                    x_tenant_id=tenant_id,
                    db=db,
                )
                result["corroboration"] = corroboration
                official_claims = list(corroboration.get("research", {}).get("claims", []))
                reconciliation, reconciliation_counts = _buyer_claim_reconciliation(
                    accepted, official_claims,
                )
                result["buyer_claim_reconciliation"] = reconciliation
                result["buyer_claim_reconciliation_status_counts"] = reconciliation_counts
                corroboration["buyer_claim_reconciliation"] = reconciliation
                corroboration["buyer_claim_reconciliation_status_counts"] = reconciliation_counts
                if corroboration.get("evidence_outcome") == "context_only":
                    # Context-only publisher material must not erase the useful,
                    # explicitly accepted buyer constraints. Keep their shelf
                    # provisional and expose the research outcome separately.
                    result["product_shelves"]["evidence_status"] = "context_only"
                    result["product_shelves"]["official_claim_count"] = 0
                    result["product_shelves"]["buyer_accepted_claim_count"] = len(accepted)
                    result["product_shelves"]["context_claim_count"] = len(
                        corroboration.get("research", {}).get("context_claims", [])
                    )
                    result["product_shelves"]["research_delta"] = []
                    corroboration["product_shelves"] = result["product_shelves"]
                else:
                    official_projection = corroboration["product_shelves"]
                    combined_projection = project_accepted_catalog(
                        db,
                        accepted_claims=[*accepted, *official_claims],
                        desired_outcome=case.retained_purpose or "Buyer accepted requirements",
                        tenant_id=tenant_id,
                        candidate_configuration_ids=_case_catalog_candidate_set_from_trace(
                            db, case_id=case_id, tenant_id=tenant_id,
                        ).configuration_ids,
                        hypothesis_labels={
                            row.hypothesis_id: row.label for row in plan.hypotheses
                        },
                    ).model_dump(mode="json")
                    for key in (
                        "evidence_status", "research_delta", "official_claim_count",
                        "context_claim_count",
                    ):
                        if key in official_projection:
                            combined_projection[key] = official_projection[key]
                    combined_projection["buyer_accepted_claim_count"] = len(accepted)
                    result["product_shelves"] = combined_projection
                    corroboration["product_shelves"] = combined_projection
                result["product_shelves"]["buyer_claim_reconciliation"] = reconciliation
                result["product_shelves"][
                    "buyer_claim_reconciliation_status_counts"
                ] = reconciliation_counts
                result["provider_accounting"] = corroboration["research"]["provider_accounting"]
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
                result["corroboration"] = {
                    "status": "blocked", "reason": detail.get("code", "research_failed"),
                    "message": detail.get("message", "The accepted claims remain provisional."),
                }
    # Ensure the JSON remains serializable before making the state transition durable.
    json.dumps(result, sort_keys=True)
    proposal.version += 1
    proposal.status = result["status"]
    proposal.acceptance_json = result
    proposal.acceptance_idempotency_key = idempotency_key
    proposal.updated_at = _now()
    db.commit()
    try:
        log_trace_event(
            trace_id=result["trace_id"],
            event_type="buyer_requirement_proposal_accepted",
            source_type="buyer",
            source_id=body.uid,
            target_type="stage",
            target_id="Requirement_Acceptance",
            payload={
                "case_id": case_id, "proposal_id": proposal_id,
                "proposal_version": result["proposal_version"],
                "status": result["status"], "research_choice": body.research_choice,
                "accepted_claim_ids": [item["claim_id"] for item in accepted],
                "rejected_claim_ids": sorted(rejected_ids),
                "qualification_authority": result["qualification_authority"],
                "cart_authority": "none",
                "provider_accounting": result["provider_accounting"],
                "shelf_ids": [shelf["shelf_id"] for shelf in result["product_shelves"]["shelves"]],
            },
        )
    except Exception:
        # Acceptance is already durably audited in the proposal row. The trace
        # projection is additive and must not make the buyer repeat the action.
        pass
    return result


@router.post("/{case_id}/fulfillment-options")
def fulfillment_options(
    case_id: str,
    body: FulfillmentOptionsRequest,
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    tenant_id = _tenant(x_tenant_id)
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="shopping_case_not_found")
    if case.uid != body.uid:
        raise HTTPException(status_code=403, detail="shopping_case_not_owned")
    choices = reduce_fulfillment_choices(
        requested_quantity=body.requested_quantity, available_now=body.available_now,
        known_lead_time_days=body.known_lead_time_days, deadline_days=body.deadline_days,
        has_next_best=body.has_next_best,
        has_architecture_alternative=body.has_architecture_alternative,
    )
    return {
        "case_id": case_id, "status": "buyer_choice_required",
        "choices": [choice.model_dump(mode="json") for choice in choices],
        "cart_mutation": "not_authorized", "supplier_send": "not_authorized",
    }


@router.post("/{case_id}/fulfillment-selections", status_code=201)
def select_fulfillment_continuation(
    case_id: str,
    body: SelectFulfillmentContinuationRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Persist a buyer choice and expose normalized, non-sent fixture offers."""
    from src.app.services.shopping_case_supplier_continuation import (
        certification_fixture_offers, select_fulfillment_option,
    )

    tenant_id = _tenant(x_tenant_id)
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="shopping_case_not_found")
    if case.uid != body.uid:
        raise HTTPException(status_code=403, detail="shopping_case_not_owned")
    if body.available_now > body.requested_quantity:
        raise HTTPException(status_code=422, detail="available_now_exceeds_requested_quantity")
    if body.choice in {"next_best_now", "substitute"} and not body.substitute_sku:
        raise HTTPException(status_code=422, detail="explicit_substitute_sku_required")
    offers = certification_fixture_offers(
        case_id=case_id, preferred_sku=body.preferred_sku,
        substitute_sku=body.substitute_sku,
        requested_quantity=body.requested_quantity, available_now=body.available_now,
    )
    selected, error = select_fulfillment_option(
        db, tenant_id=tenant_id, case_id=case_id, uid=body.uid,
        expected_revision=body.expected_revision, choice=body.choice,
        preferred_sku=body.preferred_sku,
        requested_quantity=body.requested_quantity, available_now=body.available_now,
        idempotency_key=idempotency_key, offers=offers,
        deadline_days=body.deadline_days,
    )
    if error:
        raise HTTPException(status_code=409, detail={"code": error})
    assert selected is not None
    try:
        counts: dict[str, int] = {}
        for offer in selected.offers:
            counts[offer.response_status] = counts.get(offer.response_status, 0) + 1
        log_trace_event(
            trace_id=case_id.removeprefix("sc-"),
            event_type="supplier_responses_normalized",
            source_type="deterministic_reducer",
            source_id=selected.selection_id,
            target_type="shopping_case",
            target_id=case_id,
            payload={
                "execution": "deterministic_fixture_responses_normalized",
                "evidence": {"response_status_counts": counts},
                "decision": "buyer_choice_required",
                "resolution_owner": "buyer",
                "supplier_send": "not_performed",
                "purchase_commitment": False,
                "cart_authority": "none",
            },
        )
    except Exception:
        pass
    return {
        **selected.model_dump(mode="json"),
        "supplier_send": "not_performed",
        "rfq_status": "deterministic_fixture_response_only",
        "cart_mutation": "not_authorized",
    }


@router.post("/{case_id}/fulfillment-selections/{selection_id}/confirm-cart")
def confirm_fulfillment_cart(
    case_id: str,
    selection_id: str,
    body: ConfirmFulfillmentCartRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Apply exactly one revision-bound cart set after explicit buyer confirmation."""
    from src.app.domain.cart_mutation import CartMutationPlan, CartOp
    from src.app.models.orm import Product
    from src.app.routers.cart import _get_or_create_cart
    from src.app.services.cart_mutation_service import apply_plan, propose_plan
    from src.app.services.shopping_case_supplier_continuation import (
        get_confirmation_replay, get_fulfillment_selection,
        record_cart_confirmation, resolve_confirmed_cart_target,
    )

    tenant_id = _tenant(x_tenant_id)
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="shopping_case_not_found")
    if case.uid != body.uid:
        raise HTTPException(status_code=403, detail="shopping_case_not_owned")
    replay = get_confirmation_replay(
        db, tenant_id=tenant_id, case_id=case_id, selection_id=selection_id,
        uid=body.uid, idempotency_key=idempotency_key,
    )
    if replay is not None:
        return {
            **replay.model_dump(mode="json"), "idempotent_replay": True,
            "supplier_send": "not_performed",
        }
    selection = get_fulfillment_selection(
        db, tenant_id=tenant_id, case_id=case_id, selection_id=selection_id, uid=body.uid,
    )
    if selection is None:
        raise HTTPException(status_code=404, detail="fulfillment_selection_not_found")
    if selection.revision != body.expected_revision:
        raise HTTPException(status_code=409, detail={
            "code": "stale_fulfillment_revision", "current_revision": selection.revision,
        })
    try:
        target_sku, quantity, offer = resolve_confirmed_cart_target(
            selection, selected_offer_id=body.selected_offer_id,
            substitution_authorized=body.substitution_authorized,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    product = db.execute(select(Product).where(
        Product.sku == target_sku, Product.active.is_(True),
    )).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=409, detail={
            "code": "configuration_not_commercially_enrolled", "sku": target_sku,
        })
    _cart_id, items, _updated = _get_or_create_cart(body.uid, tenant_id=tenant_id)
    previous = next((int(row.get("quantity") or 0) for row in items if row.get("sku") == target_sku), 0)
    plan = CartMutationPlan(ops=(CartOp(
        action="set_quantity", target_skus=(target_sku,), quantity=quantity,
        previous_quantity=previous, unit_price_cents=product.price_cents,
        allow_sourcing=selection.choice in {
            "split_delivery", "wait_preferred", "supplier_enquiry",
            "next_best_now", "substitute",
        },
    ),), confidence=1.0, source="shopping_case_fulfillment_confirmation")
    proposed = propose_plan(
        tenant_id=tenant_id, uid=body.uid, plan=plan, cart_items=items,
        query=(
            f"case {case_id} selection {selection_id} revision {selection.revision}: "
            f"set exact target {target_sku} to {quantity}"
        ), trace_id=case_id.removeprefix("sc-"),
    )
    applied = apply_plan(proposed["plan_id"], tenant_id=tenant_id, uid=body.uid)
    if applied.get("status") not in {"applied", "already_applied"}:
        raise HTTPException(status_code=409, detail={
            "code": "cart_confirmation_not_applied", "cart_result": applied,
        })
    recorded, error = record_cart_confirmation(
        db, tenant_id=tenant_id, case_id=case_id, selection_id=selection_id,
        uid=body.uid, expected_revision=selection.revision,
        idempotency_key=idempotency_key, selected_offer_id=body.selected_offer_id,
        cart_plan_id=proposed["plan_id"], cart_result=applied,
    )
    if error:
        raise HTTPException(status_code=409, detail={"code": error})
    assert recorded is not None
    try:
        log_trace_event(
            trace_id=case_id.removeprefix("sc-"),
            event_type="fulfillment_cart_change_confirmed",
            source_type="buyer",
            source_id=body.uid,
            target_type="shopping_case",
            target_id=case_id,
            payload={
                "execution": "revision_bound_cart_plan_applied",
                "evidence": {
                    "selected_offer_id": body.selected_offer_id,
                    "supplier_offer_provenance": offer.provenance if offer else None,
                },
                "decision": "explicit_cart_change_confirmed",
                "confirmed_sku": target_sku,
                "confirmed_quantity": quantity,
                "substitution_authorized": bool(
                    offer and offer.relationship == "compatible_substitute"
                ),
                "supplier_send": "not_performed",
                "purchase_commitment": False,
                "resolution_owner": "buyer",
            },
        )
    except Exception:
        pass
    return {
        **recorded.model_dump(mode="json"),
        "confirmed_sku": target_sku, "confirmed_quantity": quantity,
        "substitution_authorized": bool(offer and offer.relationship == "compatible_substitute"),
        "supplier_offer_provenance": offer.provenance if offer else None,
        "supplier_send": "not_performed", "idempotent_replay": False,
    }


@router.post("/{case_id}/evidence-source-resolutions")
def resolve_case_evidence_source(
    case_id: str,
    body: ResolveBuyerEvidenceSourceRequest,
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Resolve, and optionally research, one buyer-provided official-source hint.

    Resolution itself is local and free. Network retrieval only occurs when the
    buyer explicitly authorizes it, and then only against the registry's
    reviewed canonical origin. An arbitrary same-domain page never gains
    authority merely because the buyer pasted it.
    """

    from src.app.services.buyer_evidence_source_resolution import (
        resolve_buyer_evidence_source,
    )
    from src.app.services.official_source_governance import load_official_source_manifest

    tenant_id = _tenant(x_tenant_id)
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="shopping_case_not_found")
    if case.uid != body.uid:
        raise HTTPException(status_code=403, detail="shopping_case_not_owned")
    sources = list(load_official_source_manifest().get("sources") or [])
    resolution = resolve_buyer_evidence_source(
        source_url=body.source_url, vendor_name=body.vendor_name, sources=sources,
    )
    base = {
        "schema_version": "buyer-evidence-source-resolution-v1",
        "case_id": case_id, "trace_id": case_id.removeprefix("sc-"),
        "resolution": resolution.model_dump(mode="json"),
        "research_status": "not_authorized",
        "provider_accounting": {"external_calls": 0, "paid_calls": 0},
        "cart_mutation": "not_authorized", "supplier_send": "not_authorized",
    }
    if resolution.status != "resolved" or not body.research_authorized:
        return base
    if (
        _case_trace_has_event(
            db, case_id=case_id, tenant_id=tenant_id,
            event_type="buyer_evidence_source_researched",
        )
        and not body.refresh_authorized
    ):
        raise HTTPException(status_code=409, detail={
            "code": "buyer_evidence_source_already_researched",
            "message": "This case already researched a buyer-provided source. Explicitly authorize refresh to run it again.",
        })
    selected = next(
        source for source in sources if source.get("source_id") == resolution.selected_source_id
    )
    from src.app.services.official_workload_research import (
        DEFAULT_OFFICIAL_EVIDENCE_CACHE, research_official_sources,
    )

    research = research_official_sources(
        case.retained_purpose or "Buyer supplied evidence source",
        search_url_template="", sources=[selected], tenant_id=tenant_id,
        evidence_cache=DEFAULT_OFFICIAL_EVIDENCE_CACHE,
    )
    shelves = project_accepted_catalog(
        db, accepted_claims=list(research.get("claims") or []),
        desired_outcome=case.retained_purpose or "Buyer supplied evidence source",
        tenant_id=tenant_id,
        candidate_configuration_ids=_case_catalog_candidate_set_from_trace(
            db, case_id=case_id, tenant_id=tenant_id,
        ).configuration_ids,
    ).model_dump(mode="json")
    evidence_outcome = str(research.get("evidence_outcome") or "unresolved")
    result = {
        **base, "research_status": "completed",
        "provider_accounting": research.get("provider_accounting") or {
            "external_calls": 0, "paid_calls": 0,
        },
        "research": research, "evidence_outcome": evidence_outcome,
        "product_shelves": shelves,
    }
    try:
        log_trace_event(
            trace_id=result["trace_id"], event_type="buyer_evidence_source_researched",
            source_type="stage", source_id="Buyer_Evidence_Source_Resolution",
            target_type="shopping_case", target_id=case_id,
            payload={
                "case_id": case_id, "resolution": result["resolution"],
                "evidence_outcome": evidence_outcome,
                "official_claims": research.get("claims") or [],
                "context_claims": research.get("context_claims") or [],
                "receipts": research.get("receipts") or [],
                "evidence_ladder": research.get("evidence_ladder") or [],
                "provider_accounting": result["provider_accounting"],
                "cart_authority": "none", "supplier_authority": "none",
            },
        )
    except Exception:
        # Evidence and cart truth must not depend on optional trace transport.
        pass
    return result


@router.post("/{case_id}/publisher-candidates/{candidate_id}/approve")
def approve_case_publisher_candidate(
    case_id: str,
    candidate_id: str,
    body: ApprovePublisherCandidateRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Approve one discovered origin for this case, fetch it, and propose claims for review.

    The action does not enroll the publisher globally. It authorizes one exact
    origin fetch and produces reviewable requirements; cart and supplier
    authority remain absent.
    """

    tenant_id = _tenant(x_tenant_id)
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id,
        ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="shopping_case_not_found")
    if case.uid != body.uid:
        raise HTTPException(status_code=403, detail="shopping_case_not_owned")
    candidate = db.execute(select(ShoppingCasePublisherCandidate).where(
        ShoppingCasePublisherCandidate.tenant_id == tenant_id,
        ShoppingCasePublisherCandidate.case_id == case_id,
        ShoppingCasePublisherCandidate.candidate_id == candidate_id,
    )).scalar_one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="publisher_candidate_not_found")
    if (
        candidate.approval_idempotency_key == idempotency_key
        and candidate.research_result_json
    ):
        return candidate.research_result_json

    from src.app.services.case_publisher_candidate_workflow import (
        execute_case_candidate_research,
    )

    result, error = execute_case_candidate_research(
        db, candidate=candidate, case=case, tenant_id=tenant_id, uid=body.uid,
        expected_version=body.expected_candidate_version,
        idempotency_key=idempotency_key,
        allowed_claim_types=body.allowed_claim_types,
    )
    if error:
        status_code = 403 if error == "publisher_candidate_not_owned" else 409
        raise HTTPException(status_code=status_code, detail={"code": error})
    assert result is not None
    try:
        log_trace_event(
            trace_id=result["trace_id"],
            event_type="case_publisher_origin_researched",
            source_type="buyer",
            source_id=body.uid,
            target_type="shopping_case",
            target_id=case_id,
            payload={
                "candidate_id": candidate.candidate_id,
                "approval_scope": "case_only",
                "publisher_ownership_status": "buyer_attested_not_independently_verified",
                "official_claims_pending_review": result["claims"],
                "receipts": result["research"].get("receipts") or [],
                "provider_accounting": result["provider_accounting"],
                "qualification_authority": "none",
                "cart_authority": "none",
            },
        )
    except Exception:
        pass
    return result


@router.post("/{case_id}/research")
def research_shopping_case(
    case_id: str,
    body: ResearchShoppingCaseRequest,
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Run buyer-authorized live research and rerank inside one durable case."""
    tenant_id = _tenant(x_tenant_id)
    plan = _case_research_plan_from_trace(db, case_id=case_id, tenant_id=tenant_id)
    if plan is None:
        raise HTTPException(status_code=409, detail={
            "code": "case_research_plan_not_found",
            "message": "The case has no durable ambiguity proposal to authorize.",
        })
    expected_ambiguities = {row.ambiguity_id for row in plan.ambiguities}
    expected_hypotheses = {row.hypothesis_id for row in plan.hypotheses}
    if (
        body.research_plan_id != plan.plan_id
        or set(body.ambiguity_object_ids) != expected_ambiguities
        or set(body.hypothesis_ids) != expected_hypotheses
    ):
        raise HTTPException(status_code=409, detail={
            "code": "case_research_plan_mismatch",
            "message": "The submitted interpretation does not match the retained case plan.",
        })
    if (
        _case_trace_has_event(
            db, case_id=case_id, tenant_id=tenant_id,
            event_type="official_research_rerank_completed",
        )
        and not body.refresh_authorized
    ):
        raise HTTPException(status_code=409, detail={
            "code": "research_already_completed",
            "message": "Research already completed for this case. Explicitly authorize a refresh to run it again.",
        })
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is not None and case.uid != body.uid:
        raise HTTPException(status_code=403, detail="shopping_case_not_owned")
    if case is None:
        case = ShoppingCase(
            case_id=case_id, tenant_id=tenant_id, uid=body.uid, status="active",
            retained_purpose=plan.retained_purpose, created_at=_now(), updated_at=_now(),
        )
        db.add(case)
        db.flush()
    from src.app.services.case_research_plan import (
        approved_sources_for_plan, plan_hypothesis_labels,
    )
    from src.app.services.official_workload_research import (
        DEFAULT_OFFICIAL_EVIDENCE_CACHE, ranking_delta, research_official_sources,
    )

    approved_sources = approved_sources_for_plan(plan)
    from src.app.services.shopping_case_research_contract import (
        project_research_execution_contract,
    )

    if plan.publisher_status == "unresolved":
        from src.app.services.shopping_case_open_world_research import (
            OpenWorldResearchUnavailable,
            execute_open_world_publisher_discovery,
        )

        try:
            return execute_open_world_publisher_discovery(
                db,
                plan=plan,
                tenant_id=tenant_id,
                case_id=case_id,
                uid=body.uid,
                search_url_template=str(
                    os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or ""
                ).strip(),
                runtime_status=_external_research_runtime_status(),
                candidate_configuration_ids=_case_catalog_candidate_set_from_trace(
                    db, case_id=case_id, tenant_id=tenant_id,
                ).configuration_ids,
                budget_cents=body.budget_cents,
            )
        except OpenWorldResearchUnavailable as exc:
            raise HTTPException(status_code=503, detail={
                "code": exc.code,
                "message": (
                    "Open-world publisher discovery is unavailable. Upload, link, or enter "
                    "requirements; no provider call was dispatched."
                ),
                "readiness": exc.readiness,
            }) from exc
    if not approved_sources:
        raise HTTPException(status_code=409, detail={
            "code": "publisher_policy_review_required",
            "message": "Applicable publisher sources exist, but none is approved for this tenant.",
            "source_candidate_ids": plan.source_candidate_ids,
        })
    invalid_source_policies = [
        str(source.get("source_id") or "unknown")
        for source in approved_sources
        if (
            source.get("review_status") != "approved"
            or int(source.get("freshness_sla_hours") or 0) <= 0
            or (source.get("publisher_policy") or {}).get("direct_origin_required") is not True
        )
    ]
    if invalid_source_policies:
        raise HTTPException(status_code=409, detail={
            "code": "publisher_policy_or_freshness_not_enrolled",
            "message": "Applicable sources lack an approved direct-origin policy or freshness SLA.",
            "source_ids": invalid_source_policies,
        })

    source_domains = sorted({
        str(domain).strip().lower()
        for source in approved_sources
        for domain in source.get("allowed_domains") or []
        if str(domain).strip()
    })
    readiness = external_search_readiness(
        allowlist=source_domains,
        tenant_id=tenant_id,
        runtime_status=_external_research_runtime_status(),
    )
    canonical_direct_ready = all(
        bool(source.get("canonical_entrypoints")) for source in approved_sources
    )
    hard_readiness_errors = {
        "external_research_disabled",
        "external_research_tenant_not_enrolled",
        "discovery_domain_allowlist_not_configured",
    }
    if not readiness["effective"] and (
        readiness.get("error_code") in hard_readiness_errors
        or not canonical_direct_ready
    ):
        code = str(readiness.get("error_code") or "external_research_degraded")
        messages = {
            "external_research_disabled": "Approved-source research is disabled by operator policy.",
            "discovery_endpoint_not_configured": (
                "The discovery endpoint is not configured. Upload requirements or ask an operator "
                "to enroll a SearXNG-compatible endpoint."
            ),
            "discovery_endpoint_unreachable": (
                "The configured discovery endpoint was observed as unreachable."
            ),
            "discovery_endpoint_degraded": (
                "The configured discovery endpoint is degraded; no research call was dispatched."
            ),
            "discovery_reachability_not_observed": (
                "Discovery is configured but has no successful reachability observation."
            ),
            "external_research_tenant_not_enrolled": (
                "This tenant is not enrolled for approved-source research."
            ),
        }
        raise HTTPException(
            status_code=(403 if code == "external_research_tenant_not_enrolled" else 503),
            detail={
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
    search_url = (
        str(os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or "").strip()
        if readiness["effective"] else ""
    )

    before = project_accepted_catalog(
        db, accepted_claims=[], desired_outcome=plan.retained_purpose,
        budget_cents=body.budget_cents, tenant_id=tenant_id,
        candidate_configuration_ids=_case_catalog_candidate_set_from_trace(
            db, case_id=case_id, tenant_id=tenant_id,
        ).configuration_ids,
    ).model_dump(mode="json")
    research = research_official_sources(
        plan.retained_purpose, search_url_template=search_url,
        sources=list(approved_sources), plan_id=plan.plan_id,
        hypothesis_ids=body.hypothesis_ids,
        tenant_id=tenant_id,
        evidence_cache=DEFAULT_OFFICIAL_EVIDENCE_CACHE,
    )
    research["discovery_readiness"] = {
        key: readiness.get(key) for key in (
            "configured", "reachable", "effective", "degraded", "capability_status",
            "error_code", "last_discovery_success_at", "last_discovery_result_count",
        )
    }
    research["canonical_direct_ready"] = canonical_direct_ready
    record_external_research_runtime_observation(research)
    after_projection = project_accepted_catalog(
        db, accepted_claims=research["claims"], desired_outcome=plan.retained_purpose,
        budget_cents=body.budget_cents, tenant_id=tenant_id,
        candidate_configuration_ids=_case_catalog_candidate_set_from_trace(
            db, case_id=case_id, tenant_id=tenant_id,
        ).configuration_ids,
        hypothesis_labels=plan_hypothesis_labels(plan),
        hypothesis_claims={
            hypothesis.hypothesis_id: [
                claim for claim in research["claims"]
                if str(claim.get("source_id") or "") in set(hypothesis.source_ids)
            ]
            for hypothesis in plan.hypotheses
        },
    ).model_dump(mode="json")
    delta = ranking_delta(before, after_projection)
    evidence_outcome = str(research.get("evidence_outcome") or (
        "product_requirements" if research["claims"]
        else "context_only" if research["context_claims"]
        else "unresolved"
    ))
    evidence_status = (
        "researched" if evidence_outcome == "product_requirements" else evidence_outcome
    )
    research_contract = project_research_execution_contract(
        plan,
        requirements_compiled=evidence_outcome == "product_requirements",
    ).model_dump(mode="json")
    research["research_plan_id"] = plan.plan_id
    research["execution_contract"] = research_contract
    after_projection.update({
        "evidence_status": evidence_status,
        "research_delta": delta,
        "official_claim_count": len(research["claims"]),
        "context_claim_count": len(research["context_claims"]),
    })
    from src.app.services.research_explainability_projection import (
        project_research_explainability,
    )

    buyer_receipt, narration_projection = project_research_explainability(
        purpose=plan.retained_purpose, research=research,
        shelves=after_projection, delta=delta,
    )
    after_projection["research_receipt"] = buyer_receipt.model_dump(mode="json")
    after_projection["narration_projection"] = narration_projection.model_dump(mode="json")
    research_execution_mode = str(research.get("execution_mode") or "").strip().lower()
    provider_accounting = research.get("provider_accounting") or {}
    if research_execution_mode == "evidence_cache" or (
        int(provider_accounting.get("cache_hits") or 0) > 0
        and int(provider_accounting.get("external_calls") or 0) == 0
    ):
        research_execution = "governed_evidence_cache_hit"
    elif research_execution_mode == "live_network" or int(
        provider_accounting.get("external_calls") or 0
    ) > 0:
        research_execution = "live_official_research_completed"
    elif research_execution_mode == "not_executed":
        research_execution = "official_research_not_executed"
    else:
        research_execution = "governed_official_research_completed"
    from src.app.services.shopping_case_truth_projection import ShoppingCaseTruthProjection

    exploration = ShoppingCaseTruthProjection.model_validate({
        "schema_version": "ambiguity-exploration-v1",
        "case_id": case_id, "trace_id": case_id.removeprefix("sc-"),
        "retained_purpose": plan.retained_purpose,
        "status": evidence_status,
        "interpretations": [row.model_dump(mode="json") for row in plan.hypotheses],
        "next_question": {"id": "research_scope", "text": plan.next_question},
        "execution": research_execution,
        "evidence": (
            "scoped_product_requirements_compiled"
            if evidence_outcome == "product_requirements"
            else "authoritative_context_only"
            if evidence_outcome == "context_only"
            else "no_accepted_claims"
        ),
        "decision": (
            "conditional_fit_allowed"
            if evidence_outcome == "product_requirements"
            else "provisional_exploration_only"
        ),
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
                    and evidence_outcome != "product_requirements"
                    else row.status
                ),
            }
            for row in plan.obligations
        ],
        "source_candidate_ids": list(plan.source_candidate_ids),
    }).model_dump(mode="json")
    result = {
        "schema_version": "shopping-case-research-v1", "case_id": case_id,
        "status": "research_completed", "retained_purpose": plan.retained_purpose,
        "research_plan": plan.model_dump(mode="json"),
        "research_contract": research_contract,
        "research": research, "product_shelves": after_projection,
        "ambiguity_exploration": exploration,
        "evidence_outcome": evidence_outcome,
        "research_delta": delta, "cart_mutation": "not_authorized",
        "supplier_send": "not_authorized", "trace_id": case_id.removeprefix("sc-"),
    }
    case.retained_purpose = plan.retained_purpose
    case.updated_at = _now()
    db.commit()
    try:
        log_trace_event(
            trace_id=result["trace_id"], event_type="official_research_rerank_completed",
            source_type="stage", source_id="Governed_Official_Research",
            target_type="shopping_case", target_id=case_id,
            payload={
                "case_id": case_id, "status": result["status"],
                "provider_accounting": research["provider_accounting"],
                "receipts": research["receipts"], "research_delta": delta,
                "evidence_ladder": research.get("evidence_ladder", []),
                "source_execution": research.get("source_execution", []),
                "official_claims": research["claims"],
                "context_claims": research["context_claims"],
                "evidence_outcome": evidence_outcome,
                "cart_authority": "none", "supplier_authority": "none",
            },
        )
    except Exception:
        pass
    return result


@router.post("/{case_id}/cart-proposals")
def propose_case_cart_mutation(
    case_id: str,
    body: ProposeCaseCartMutationRequest,
    x_tenant_id: str | None = Header(default=None),
    db=Depends(get_db),
) -> dict[str, Any]:
    """Create an explicit-confirmation plan; never mutate the cart here."""
    from src.app.domain.cart_mutation import CartMutationPlan, CartOp
    from src.app.models.orm import Product
    from src.app.routers.cart import _get_or_create_cart
    from src.app.services.cart_mutation_service import propose_plan

    tenant_id = _tenant(x_tenant_id)
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="shopping_case_not_found")
    if case.uid != body.uid:
        raise HTTPException(status_code=403, detail="shopping_case_not_owned")
    product = db.execute(select(Product).where(
        Product.sku == body.sku, Product.active.is_(True),
    )).scalar_one_or_none()
    if product is None:
        raise HTTPException(status_code=409, detail={
            "code": "configuration_not_commercially_enrolled",
            "message": "This exact configuration can be researched but is not enrolled for cart or supplier action.",
        })
    _cart_id, items, _updated = _get_or_create_cart(body.uid, tenant_id=tenant_id)
    previous = next(
        (int(row.get("quantity") or 0) for row in items if row.get("sku") == body.sku), 0,
    )
    plan = CartMutationPlan(
        ops=(CartOp(
            action="set_quantity", target_skus=(body.sku,), quantity=body.quantity,
            previous_quantity=previous, unit_price_cents=product.price_cents,
            # The reviewed source says available/built-to-order but does not attest a
            # numeric ATP quantity. Supplier sourcing therefore remains explicit.
            allow_sourcing=True,
        ),),
        confidence=1.0, source="shopping_case_verified_selection",
    )
    proposed = propose_plan(
        tenant_id=tenant_id, uid=body.uid, plan=plan, cart_items=items,
        query=f"case {case_id}: set {body.sku} to {body.quantity}",
        trace_id=case_id.removeprefix("sc-"),
    )
    return {
        "case_id": case_id, "status": "confirmation_required",
        "plan_id": proposed["plan_id"], "risk": proposed["risk"],
        "expires_at": proposed["expires_at"], "ops": [row.as_dict() for row in plan.ops],
        "cart_mutation": "not_applied", "supplier_send": "not_authorized",
    }
