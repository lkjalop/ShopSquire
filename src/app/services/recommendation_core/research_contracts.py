"""Bounded contracts between model interpretation, evidence providers and fit gates.

These types deliberately contain no product verticals, vendor names or provider IDs.  A
model may propose what evidence is needed; the platform registry decides which enrolled
provider is allowed to supply it, and deterministic compilers decide whether a claim can
become a catalog requirement.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ClaimType = Literal[
    "concept_identity",
    "minimum_requirements",
    "recommended_requirements",
    "target_requirements",
    "compatibility",
    "certification",
]
ProviderCapability = Literal[
    "concept_discovery",
    "official_requirements",
    "standards_regulatory",
    "professional_software_requirements",
    "game_requirements",
    "approved_tenant_document",
    "catalog_specification",
    "visual_identity",
    "visual_document_evidence",
]


class ResolutionOwner(str, Enum):
    """The authority expected to resolve an obligation.

    This vocabulary is deliberately about authority boundaries, not workloads.
    New workload descriptions stay open vocabulary in :class:`AmbiguityObject`.
    """

    CATALOG = "CATALOG"
    RESEARCH = "RESEARCH"
    BUYER = "BUYER"
    COMPUTATION = "COMPUTATION"
    SUPPLIER = "SUPPLIER"
    TENANT_POLICY = "TENANT_POLICY"
    HUMAN = "HUMAN"


class AmbiguityHypothesis(BaseModel):
    """One of at most three bounded, non-authoritative interpretations."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=2, max_length=200)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_needed: list[str] = Field(default_factory=list, max_length=8)
    authority: Literal["proposed"] = "proposed"


class AmbiguityObject(BaseModel):
    """An open-vocabulary uncertainty attached to the buyer-authored span.

    ``ambiguity_type`` is intentionally a bounded string rather than an enum. This
    lets the model describe unfamiliar uncertainty without teaching the reducer a
    new persona or vertical. Owners still come from the closed authority boundary.
    """

    model_config = ConfigDict(extra="forbid")

    ambiguity_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    ambiguity_type: str = Field(min_length=2, max_length=100)
    subject_span: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=2, max_length=300)
    hypotheses: list[AmbiguityHypothesis] = Field(min_length=1, max_length=3)
    shared_requirement_candidates: list[str] = Field(default_factory=list, max_length=12)
    divergent_axes: list[str] = Field(default_factory=list, max_length=8)
    resolution_owners: list[ResolutionOwner] = Field(min_length=1, max_length=4)
    material: bool = True

    @model_validator(mode="after")
    def unique_hypotheses(self) -> "AmbiguityObject":
        ids = [item.hypothesis_id for item in self.hypotheses]
        if len(ids) != len(set(ids)):
            raise ValueError("hypothesis_id values must be unique within an ambiguity")
        return self


class TurnObligation(BaseModel):
    """A separately resolvable duty produced by one buyer turn."""

    model_config = ConfigDict(extra="forbid")

    obligation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    # Open vocabulary: examples include workload meaning, budget arithmetic,
    # delivery shortfall and exact product capability.
    obligation_type: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=2, max_length=300)
    primary_owner: ResolutionOwner
    resolution_owners: list[ResolutionOwner] = Field(min_length=1, max_length=4)
    ambiguity_ids: list[str] = Field(default_factory=list, max_length=8)
    status: Literal["unresolved", "planned", "resolved", "blocked"] = "unresolved"
    material: bool = True

    @model_validator(mode="after")
    def primary_owner_is_declared(self) -> "TurnObligation":
        if self.primary_owner not in self.resolution_owners:
            raise ValueError("primary_owner must be included in resolution_owners")
        if len(self.resolution_owners) != len(set(self.resolution_owners)):
            raise ValueError("resolution_owners must be unique")
        return self


class SpanningResearchQuery(BaseModel):
    """One purpose-limited query in a bounded scatter/gather plan."""

    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    obligation_ids: list[str] = Field(min_length=1, max_length=6)
    purpose: Literal[
        "concept", "workload", "compatibility", "platform", "product_identity", "behavioural"
    ]
    subject_span: str = Field(min_length=1, max_length=160)
    query_text: str = Field(min_length=3, max_length=240)
    coverage_axes: list[str] = Field(min_length=1, max_length=6)
    allowed_claim_types: list[ClaimType] = Field(default_factory=list, max_length=6)
    max_results: int = Field(default=5, ge=1, le=10)
    authority: Literal["discovery_only"] = "discovery_only"


class SpanningQueryContract(BaseModel):
    """A complete but bounded research fan-out.

    Every declared axis must be covered by at least one query. The contract limits
    both query count and per-query results, preventing an LLM from turning one
    ambiguous request into an unbounded general-web crawl.
    """

    model_config = ConfigDict(extra="forbid")

    contract_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    required_coverage_axes: list[str] = Field(min_length=1, max_length=8)
    queries: list[SpanningResearchQuery] = Field(min_length=1, max_length=8)
    max_queries: int = Field(default=4, ge=1, le=8)
    max_total_results: int = Field(default=24, ge=1, le=80)

    @model_validator(mode="after")
    def bounded_and_spanning(self) -> "SpanningQueryContract":
        if len(self.queries) > self.max_queries:
            raise ValueError("query count exceeds max_queries")
        ids = [item.query_id for item in self.queries]
        if len(ids) != len(set(ids)):
            raise ValueError("query_id values must be unique")
        if sum(item.max_results for item in self.queries) > self.max_total_results:
            raise ValueError("query result allowance exceeds max_total_results")
        covered = {axis for item in self.queries for axis in item.coverage_axes}
        missing = set(self.required_coverage_axes) - covered
        if missing:
            raise ValueError(f"required coverage axes are not spanned: {sorted(missing)}")
        return self


ExecutionStatus = Literal[
    "planned",
    "rejected_admission",
    "not_dispatched",
    "dispatched",
    "completed",
    "failed",
    "timed_out",
]


class ProviderExecutionReceipt(BaseModel):
    """Auditable truth about discovery or authoritative-origin execution.

    A provider being configured or selected is not execution. A fixture completion,
    cache hit and real outbound request are represented distinctly and cannot be
    projected into one another by UI code.
    """

    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    execution_id: str = Field(min_length=1, max_length=128)
    provider_capability: Literal["WEB_DISCOVERY", "OFFICIAL_ORIGIN_FETCH"]
    provider_id: str = Field(min_length=1, max_length=160)
    certification_run_id: str | None = Field(default=None, max_length=128)
    provider_endpoint_host: str | None = Field(default=None, max_length=253)
    query_id: str | None = Field(default=None, max_length=64)
    query_hash: str | None = Field(default=None, min_length=8, max_length=128)
    query_purpose: str | None = Field(default=None, max_length=80)
    obligation_ids: list[str] = Field(default_factory=list, max_length=8)
    execution_status: ExecutionStatus
    fixture: bool
    network_execution: bool
    external_call_dispatched: bool
    cache_status: Literal["not_checked", "miss", "fresh_hit", "stale_revalidate"]
    billing_class: Literal["free", "paid", "unknown", "not_applicable"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    http_status: int | None = Field(default=None, ge=100, le=599)
    result_count: int | None = Field(default=None, ge=0)
    allowlisted_result_count: int | None = Field(default=None, ge=0)
    response_body_hash: str | None = Field(default=None, min_length=8, max_length=128)
    selected_origin_urls: list[str] = Field(default_factory=list, max_length=12)
    origin_content_type: str | None = Field(default=None, max_length=160)
    origin_observed_at: datetime | None = None
    rejection_reason: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def execution_truth_is_coherent(self) -> "ProviderExecutionReceipt":
        unexecuted = self.execution_status in {
            "planned", "rejected_admission", "not_dispatched"
        }
        if unexecuted:
            if self.external_call_dispatched or self.network_execution:
                raise ValueError("unexecuted receipt cannot claim dispatch or network execution")
            if any((
                self.started_at,
                self.completed_at,
                self.http_status,
                self.response_body_hash,
                self.selected_origin_urls,
                self.origin_content_type,
                self.origin_observed_at,
            )):
                raise ValueError("unexecuted receipt cannot carry execution observations")
        if self.execution_status == "rejected_admission" and not self.rejection_reason:
            raise ValueError("rejected admission requires rejection_reason")
        if self.network_execution and (
            self.fixture or not self.external_call_dispatched
        ):
            raise ValueError("network execution must be non-fixture and externally dispatched")
        if self.fixture and (self.network_execution or self.external_call_dispatched):
            raise ValueError("fixture receipt cannot claim an external network dispatch")
        if self.cache_status == "fresh_hit" and (
            self.network_execution or self.external_call_dispatched
        ):
            raise ValueError("fresh cache hit cannot claim a new external call")
        if self.execution_status == "completed":
            completed_by_cache = self.cache_status == "fresh_hit"
            if not (self.fixture or self.network_execution or completed_by_cache):
                raise ValueError("completed receipt needs fixture, network, or cache evidence")
            if self.started_at is None or self.completed_at is None:
                raise ValueError("completed receipt requires start and completion timestamps")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at cannot precede started_at")
        if self.certification_run_id and self.network_execution:
            certification_observations = (
                self.provider_endpoint_host,
                self.query_hash,
                self.http_status,
                self.response_body_hash,
            )
            if any(value is None for value in certification_observations):
                raise ValueError(
                    "live certification receipt requires endpoint, query hash, HTTP status, "
                    "and response hash"
                )
        if self.billing_class == "paid" and not self.external_call_dispatched:
            raise ValueError("paid billing requires an externally dispatched call")
        if (
            self.allowlisted_result_count is not None
            and self.result_count is not None
            and self.allowlisted_result_count > self.result_count
        ):
            raise ValueError("allowlisted_result_count cannot exceed result_count")
        return self

    @property
    def trace_execution_state(self) -> Literal["pending", "rejected", "not_executed", "running", "completed", "failed"]:
        return {
            "planned": "pending",
            "rejected_admission": "rejected",
            "not_dispatched": "not_executed",
            "dispatched": "running",
            "completed": "completed",
            "failed": "failed",
            "timed_out": "failed",
        }[self.execution_status]

    def as_trace_dict(self) -> dict[str, Any]:
        """Return the UI-safe execution projection without reinterpreting state."""

        return {
            "receipt_id": self.receipt_id,
            "execution_id": self.execution_id,
            "provider_capability": self.provider_capability,
            "provider_id": self.provider_id,
            "execution": self.trace_execution_state,
            "fixture": self.fixture,
            "network_execution": self.network_execution,
            "external_call_dispatched": self.external_call_dispatched,
            "cache_status": self.cache_status,
            "billing_class": self.billing_class,
            "http_status": self.http_status,
            "result_count": self.result_count,
            "allowlisted_result_count": self.allowlisted_result_count,
            "rejection_reason": self.rejection_reason,
        }


class ResearchTurnContract(BaseModel):
    """All independently-owned obligations generated by one turn."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["research-turn-v1"] = "research-turn-v1"
    turn_id: str = Field(min_length=1, max_length=128)
    ambiguities: list[AmbiguityObject] = Field(default_factory=list, max_length=8)
    obligations: list[TurnObligation] = Field(min_length=1, max_length=16)
    query_contract: SpanningQueryContract | None = None

    @model_validator(mode="after")
    def references_exist(self) -> "ResearchTurnContract":
        ambiguity_ids = {item.ambiguity_id for item in self.ambiguities}
        obligation_ids = {item.obligation_id for item in self.obligations}
        if len(obligation_ids) != len(self.obligations):
            raise ValueError("obligation_id values must be unique")
        unknown_ambiguities = {
            ambiguity_id
            for item in self.obligations
            for ambiguity_id in item.ambiguity_ids
            if ambiguity_id not in ambiguity_ids
        }
        if unknown_ambiguities:
            raise ValueError(f"unknown ambiguity references: {sorted(unknown_ambiguities)}")
        if self.query_contract:
            unknown_obligations = {
                obligation_id
                for query in self.query_contract.queries
                for obligation_id in query.obligation_ids
                if obligation_id not in obligation_ids
            }
            if unknown_obligations:
                raise ValueError(f"unknown obligation references: {sorted(unknown_obligations)}")
        return self
ResearchStatus = Literal[
    "planned",
    "not_configured",
    "not_allowed",
    "attempted_empty",
    "rejected",
    "conflicting",
    "accepted",
    "timed_out",
    "failed",
]


class ResearchQuery(BaseModel):
    """One bounded research attempt tied to an evidence need.

    Query text may contain buyer-authored spans and closed claim-purpose language only.
    Proposed hypothesis labels stay in trace metadata until evidence establishes them.
    """

    model_config = ConfigDict(extra="forbid")

    query_id: str = Field(min_length=1, max_length=64)
    evidence_need_id: str = Field(min_length=1, max_length=64)
    subject_span: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=3, max_length=240)
    strategy: Literal["identity", "requirements", "compatibility", "rewrite"]
    hypothesis_ids: list[str] = Field(default_factory=list, max_length=5)
    prohibited_assumptions: list[str] = Field(default_factory=list, max_length=8)
    authority: Literal["research_query_only"] = "research_query_only"


class EvidenceNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    need_id: str = Field(min_length=1, max_length=64)
    subject_span: str = Field(min_length=1, max_length=120)
    claim_type: ClaimType
    provider_capability: ProviderCapability
    material: bool = True
    max_age_days: int = Field(default=365, ge=1, le=3650)


class MaterialSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=3, max_length=240)
    answer_type: Literal["free_text", "enum", "number", "date", "boolean"] = "free_text"
    purpose: Literal[
        "resolve_concept",
        "resolve_compatibility",
        "resolve_performance_target",
        "resolve_product_identity",
        "resolve_safety_or_policy",
    ] = "resolve_concept"
    material: bool = True
    answer_status: Literal["unresolved", "candidate"] = "unresolved"
    answer_candidate: str | None = Field(default=None, max_length=500)


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["research-plan-v1"] = "research-plan-v1"
    interpretation_origin: Literal["model", "deterministic_fallback", "persisted"] = "model"
    subject_spans: list[str] = Field(default_factory=list, max_length=4)
    evidence_needs: list[EvidenceNeed] = Field(default_factory=list, max_length=8)
    query_bundle: list[ResearchQuery] = Field(default_factory=list, max_length=8)
    material_slots: list[MaterialSlot] = Field(default_factory=list, max_length=5)
    max_provider_fanout: int = Field(default=3, ge=1, le=4)
    per_provider_timeout_ms: int = Field(default=1800, ge=100, le=30_000)
    total_timeout_ms: int = Field(default=2000, ge=100, le=60_000)
    external_consent_required: bool = True
    external_research_authorized: bool = False


class EvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    need_id: str = Field(min_length=1, max_length=64)
    subject_span: str = Field(min_length=1, max_length=120)
    claim_type: ClaimType
    status: ResearchStatus
    source_id: str | None = Field(default=None, max_length=160)
    source_record_id: str | None = Field(default=None, max_length=240)
    observed_at: str | None = Field(default=None, max_length=80)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    value: str | float | int | bool | None = None
    unit: str | None = Field(default=None, max_length=40)
    attribute_key: str | None = Field(default=None, max_length=80)
    operator: Literal[">=", "<=", "=", "in", "contains"] | None = None
    artefact_name: str | None = Field(default=None, max_length=160)
    artefact_version: str | None = Field(default=None, max_length=80)
    requirement_class: Literal["minimum", "recommended", "target", "optimal"] | None = None
    scope_caveat: str | None = Field(default=None, max_length=500)
    source_revision: str | None = Field(default=None, max_length=160)
    freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    supersedes_claim_id: str | None = Field(default=None, max_length=240)


class CompiledRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_key: str = Field(min_length=1, max_length=80)
    operator: Literal[">=", "<=", "=", "in", "contains"]
    value: str | float | int | bool
    unit: str | None = Field(default=None, max_length=40)
    source_claim_ids: list[str] = Field(min_length=1, max_length=8)
    authority: Literal["accepted_evidence"] = "accepted_evidence"
    artefact_name: str | None = Field(default=None, max_length=160)
    artefact_version: str | None = Field(default=None, max_length=80)
    requirement_class: Literal["minimum", "recommended", "target", "optimal"] = "minimum"
    scope_caveat: str | None = Field(default=None, max_length=500)
    source_revision: str | None = Field(default=None, max_length=160)
    freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    verification_status: Literal["verified", "unverified"] = "verified"
    supersedes_claim_id: str | None = Field(default=None, max_length=240)


class BehavioralEvidenceClaim(BaseModel):
    """A measured or explicitly inferred performance observation.

    Behavioral evidence never becomes a compatibility floor. It answers a
    different question: how an exact or nearby configuration behaved under
    recorded workload settings.
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1, max_length=240)
    product_configuration_hash: str = Field(min_length=8, max_length=128)
    artefact_name: str = Field(min_length=1, max_length=160)
    artefact_version: str | None = Field(default=None, max_length=80)
    metric_key: str = Field(min_length=1, max_length=80)
    value: float
    unit: str = Field(min_length=1, max_length=40)
    settings: dict[str, Any] = Field(default_factory=dict)
    evidence_distance: Literal["exact", "near", "far", "inferred"]
    source_id: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=240)
    observed_at: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0.0, le=1.0)
    scope_caveat: str | None = Field(default=None, max_length=500)
