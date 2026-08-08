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
from src.app.models.orm import RequirementProposal, ShoppingCase
from src.app.services.buyer_requirement_evidence import ExtractedRequirementClaim
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.infrastructure_alternative_projection import project_infrastructure_alternatives
from src.app.services.evidence_acquisition_ladder import choose_evidence_stage
from src.app.services.fulfillment_choice_reducer import reduce_fulfillment_choices
from src.app.services.decision_log import log_trace_event


router = APIRouter(prefix="/api/v1/shopping-cases", tags=["shopping-cases"])


class CreateRequirementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    retained_purpose: str | None = Field(default=None, max_length=500)
    source_reference: str = Field(min_length=1, max_length=500)
    claims: list[ExtractedRequirementClaim] = Field(min_length=1, max_length=64)


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


class CreateCaseInterpretationRequest(BaseModel):
    """Buyer-authored outcome only; the server owns all research scope."""

    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    retained_purpose: str = Field(min_length=3, max_length=500)


class ProposeCaseCartMutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    sku: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=500)


def _tenant(value: str | None) -> str:
    return str(value or "default").strip() or "default"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _trace_id(proposal_id: str, version: int) -> str:
    return "req-" + hashlib.sha256(f"{proposal_id}:{version}".encode()).hexdigest()[:20]


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
        if plan is None or plan.plan_id != recorded_plan_id:
            return None
        return plan
    return None


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

    plan = build_case_research_plan(body.retained_purpose)
    if plan is None:
        return Response(status_code=204)

    tenant_id = _tenant(x_tenant_id)
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
    )
    exploration = {
        "schema_version": "ambiguity-exploration-v1",
        "case_id": case_id,
        "trace_id": trace_id,
        "retained_purpose": plan.retained_purpose,
        "status": "provisional",
        "interpretations": [
            {
                "hypothesis_id": row.hypothesis_id,
                "label": row.label,
                "authority": row.authority,
            }
            for row in plan.hypotheses
        ],
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
    }
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
        },
    )
    return {
        "schema_version": "case-interpretation-v1",
        "case_id": case_id,
        "trace_id": trace_id,
        "ambiguity_exploration": exploration,
        "product_shelves": projection.model_dump(mode="json"),
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
        item["acceptance_status"] = "accepted_provisional"
        item["authority_status"] = "unverified"
        accepted.append(item)
    result = {
        "schema_version": "requirement-acceptance-v1",
        "case_id": case_id,
        "proposal_id": proposal_id,
        "proposal_version": proposal.version + 1,
        "status": "accepted_provisional",
        "accepted_claims": accepted,
        "rejected_claim_ids": sorted(rejected_ids),
        "research_choice": body.research_choice,
        "research_authorized": body.research_choice == "research_and_corroborate",
        "qualification_authority": "none",
        "cart_mutation": "not_authorized",
        "trace_id": _trace_id(proposal_id, proposal.version + 1),
        "provider_accounting": {"external_calls": 0, "paid_calls": 0},
    }
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    )).scalar_one()
    shelves = project_accepted_catalog(
        db, accepted_claims=accepted,
        desired_outcome=case.retained_purpose or "Buyer accepted requirements",
        tenant_id=tenant_id,
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
    # Ensure the JSON remains serializable before making the state transition durable.
    json.dumps(result, sort_keys=True)
    proposal.version += 1
    proposal.status = "accepted_provisional"
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
                "qualification_authority": "none", "cart_authority": "none",
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
    search_url = str(os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or "").strip()
    if not search_url:
        raise HTTPException(status_code=503, detail={
            "code": "local_discovery_not_enrolled",
            "message": "Start the enrolled local SearXNG profile or upload requirements.",
        })
    from src.app.services.case_research_plan import (
        approved_sources_for_plan, plan_hypothesis_labels,
    )
    from src.app.services.official_workload_research import (
        ranking_delta, research_official_sources,
    )

    approved_sources = approved_sources_for_plan(plan)
    if not approved_sources:
        raise HTTPException(status_code=409, detail={
            "code": "publisher_policy_review_required",
            "message": "Applicable publisher sources exist, but none is approved for this tenant.",
            "source_candidate_ids": plan.source_candidate_ids,
        })

    before = project_accepted_catalog(
        db, accepted_claims=[], desired_outcome=plan.retained_purpose,
        budget_cents=body.budget_cents, tenant_id=tenant_id,
    ).model_dump(mode="json")
    research = research_official_sources(
        plan.retained_purpose, search_url_template=search_url,
        sources=list(approved_sources), plan_id=plan.plan_id,
        hypothesis_ids=body.hypothesis_ids,
    )
    after_projection = project_accepted_catalog(
        db, accepted_claims=research["claims"], desired_outcome=plan.retained_purpose,
        budget_cents=body.budget_cents, tenant_id=tenant_id,
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
    after_projection.update({
        "evidence_status": "researched",
        "research_delta": delta,
        "official_claim_count": len(research["claims"]),
        "context_claim_count": len(research["context_claims"]),
    })
    result = {
        "schema_version": "shopping-case-research-v1", "case_id": case_id,
        "status": "research_completed", "retained_purpose": plan.retained_purpose,
        "research_plan": plan.model_dump(mode="json"),
        "research": research, "product_shelves": after_projection,
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
                "official_claims": research["claims"],
                "context_claims": research["context_claims"],
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
