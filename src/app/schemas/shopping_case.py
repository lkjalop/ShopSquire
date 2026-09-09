"""Closed buyer request contracts for shopping-case HTTP operations."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from src.app.services.buyer_requirement_evidence import ExtractedRequirementClaim

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
    authorization_basis: Literal["buyer_action", "tenant_policy"] = "buyer_action"
    refresh_authorized: bool = False
    execution_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,80}$")
    decision_trace_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9_-]{8,200}$",
    )
    workload_kind_hints: list[Literal["game", "software"]] = Field(
        default_factory=list, max_length=3,
    )
    unresolved_concepts: list[str] = Field(default_factory=list, max_length=3)


class CancelShoppingCaseResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    execution_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    reason: Literal[
        "buyer_departed", "buyer_cancelled", "research_deadline_exceeded",
        "research_superseded",
    ]


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
    authorization_basis: Literal["buyer_action", "tenant_policy", "none"] = "none"
    refresh_authorized: bool = False


class CreateCaseInterpretationRequest(BaseModel):
    """Buyer-authored outcome only; the server owns all research scope."""

    model_config = ConfigDict(extra="forbid")
    uid: str = Field(min_length=1, max_length=200)
    retained_purpose: str = Field(min_length=3, max_length=500)
    storefront_taxonomy_handle: str | None = Field(default=None, min_length=2, max_length=160)
    session_epoch: str | None = Field(default=None, min_length=1, max_length=200)


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
