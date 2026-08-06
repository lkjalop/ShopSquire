"""Bounded contracts between model interpretation, evidence providers and fit gates.

These types deliberately contain no product verticals, vendor names or provider IDs.  A
model may propose what evidence is needed; the platform registry decides which enrolled
provider is allowed to supply it, and deterministic compilers decide whether a claim can
become a catalog requirement.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ClaimType = Literal[
    "concept_identity",
    "minimum_requirements",
    "recommended_requirements",
    "target_requirements",
    "compatibility",
    "certification",
]
ProviderCapability = Literal[
    "official_requirements",
    "approved_tenant_document",
    "catalog_specification",
    "visual_identity",
]
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


class CompiledRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_key: str = Field(min_length=1, max_length=80)
    operator: Literal[">=", "<=", "=", "in", "contains"]
    value: str | float | int | bool
    unit: str | None = Field(default=None, max_length=40)
    source_claim_ids: list[str] = Field(min_length=1, max_length=8)
    authority: Literal["accepted_evidence"] = "accepted_evidence"
