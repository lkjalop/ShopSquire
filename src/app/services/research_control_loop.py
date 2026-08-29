"""Typed research-control state, fault localization, and gated learning proposals.

This module deliberately grants no research, catalog, or commerce authority.  It
turns already-adjudicated state into replayable diagnostics and requires held-out
evidence before a sanitized experiential patch can advance beyond cold storage.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExecutionStateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["research-execution-state-v1"] = "research-execution-state-v1"
    case_id: str = Field(min_length=1, max_length=200)
    case_revision: int = Field(ge=1)
    buyer_text_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_identity: str | None = Field(default=None, max_length=200)
    model_output_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    model_status: Literal["not_attempted", "completed", "failed", "timeout", "degraded"]
    material_concept_status: Literal["not_applicable", "unresolved", "candidate", "resolved"]
    research_authority: Literal["not_requested", "required", "granted", "denied"]
    provider_status: Literal[
        "not_applicable", "not_attempted", "disabled", "timeout", "failed", "completed",
    ]
    evidence_status: Literal["none", "identity_only", "stale", "contradicted", "accepted"]
    requirement_status: Literal["not_applicable", "blocked", "provisional", "accepted"]
    catalog_authority: Literal["blocked", "provisional", "permitted"]
    presentation_status: Literal[
        "clarification_only", "provisional_exploration", "qualified_recommendation",
    ]
    commerce_authority: Literal["none", "proposal_only", "approved"]
    receipts: tuple["ControlReceipt", ...] = Field(default_factory=tuple, max_length=32)

    @model_validator(mode="after")
    def authority_invariants(self) -> "ExecutionStateEnvelope":
        if (
            self.material_concept_status in {"unresolved", "candidate"}
            and self.presentation_status == "qualified_recommendation"
        ):
            raise ValueError("presentation_exceeds_evidence_authority")
        if self.catalog_authority == "permitted" and self.requirement_status != "accepted":
            raise ValueError("catalog_authority_without_accepted_requirements")
        if self.commerce_authority == "approved" and self.catalog_authority != "permitted":
            raise ValueError("commerce_authority_without_catalog_authority")
        return self


class ControlFault(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    component: Literal["model", "working_state", "invocation", "checker", "presentation"]
    code: str = Field(min_length=1, max_length=120)
    severity: Literal["warning", "material"] = "material"
    authority: Literal["none"] = "none"


class ControlReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    component: Literal["model", "working_state", "invocation", "checker", "presentation"]
    status: str = Field(min_length=1, max_length=80)
    authority: Literal["proposes", "records", "retrieves", "authorizes", "presents"]
    reason: str = Field(min_length=1, max_length=240)


def localize_control_faults(envelope: ExecutionStateEnvelope) -> list[ControlFault]:
    faults: list[ControlFault] = []
    if envelope.model_status in {"failed", "timeout"}:
        faults.append(ControlFault(component="model", code=f"model_{envelope.model_status}"))
    if envelope.research_authority == "granted" and envelope.provider_status == "disabled":
        faults.append(ControlFault(component="invocation", code="authorized_provider_disabled"))
    elif envelope.research_authority == "granted" and envelope.provider_status == "not_attempted":
        faults.append(ControlFault(component="invocation", code="authorized_provider_not_invoked"))
    elif envelope.provider_status in {"timeout", "failed"}:
        faults.append(ControlFault(component="invocation", code=f"provider_{envelope.provider_status}"))
    if envelope.evidence_status in {"stale", "contradicted"}:
        faults.append(ControlFault(component="checker", code=f"evidence_{envelope.evidence_status}"))
    if (
        envelope.material_concept_status == "resolved"
        and envelope.evidence_status == "identity_only"
        and envelope.provider_status == "completed"
    ):
        faults.append(ControlFault(component="working_state", code="identity_resolved_requirements_missing"))
    return faults


class SanitizedFailureLesson(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lesson_id: str
    case_id: str
    case_revision: int
    buyer_text_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    raw_buyer_text: None = None
    fault_codes: tuple[str, ...]
    authority: Literal["none"] = "none"
    lifecycle: Literal["cold"] = "cold"


def propose_sanitized_failure_lesson(
    envelope: ExecutionStateEnvelope, faults: list[ControlFault],
) -> SanitizedFailureLesson:
    import hashlib

    codes = tuple(dict.fromkeys(item.code for item in faults))
    digest = hashlib.sha256(
        f"{envelope.case_id}:{envelope.case_revision}:{','.join(codes)}".encode("utf-8")
    ).hexdigest()[:20]
    return SanitizedFailureLesson(
        lesson_id=f"lesson-{digest}",
        case_id=envelope.case_id,
        case_revision=envelope.case_revision,
        buyer_text_hash=envelope.buyer_text_hash,
        fault_codes=codes,
    )


class ExperientialPatchCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_id: str = Field(min_length=1, max_length=160)
    failure_code: str = Field(min_length=1, max_length=120)
    component: Literal["model", "working_state", "invocation", "checker", "presentation"]
    proposed_change: str = Field(min_length=1, max_length=1000)
    rollback_ref: str = Field(min_length=1, max_length=240)
    provenance_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    lifecycle: Literal["cold", "warm"] = "cold"


class PromotionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    repeated_failure_count: int = Field(ge=0)
    heldout_cases: int = Field(ge=1)
    baseline_successes: int = Field(ge=0)
    candidate_successes: int = Field(ge=0)
    safety_regressions: int = Field(ge=0)

    @model_validator(mode="after")
    def bounded_counts(self) -> "PromotionEvidence":
        if self.baseline_successes > self.heldout_cases or self.candidate_successes > self.heldout_cases:
            raise ValueError("success_count_exceeds_heldout_cases")
        return self


class PromotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patch_id: str
    promoted: bool
    lifecycle: Literal["cold", "warm", "hot"]
    reasons: tuple[str, ...]
    authority: Literal["none"] = "none"
    rollback_ref: str


def promote_experiential_patch(
    candidate: ExperientialPatchCandidate, evidence: PromotionEvidence,
) -> PromotionDecision:
    reasons: list[str] = []
    if evidence.repeated_failure_count < 3:
        reasons.append("insufficient_repeated_failures")
    if evidence.heldout_cases < 5:
        reasons.append("insufficient_heldout_cases")
    if evidence.candidate_successes <= evidence.baseline_successes:
        reasons.append("no_heldout_success_gain")
    if evidence.safety_regressions:
        reasons.append("safety_regression_detected")
    promoted = not reasons
    lifecycle: Literal["cold", "warm", "hot"] = "cold"
    if promoted:
        lifecycle = (
            "hot"
            if candidate.lifecycle == "warm"
            and evidence.repeated_failure_count >= 5
            and evidence.heldout_cases >= 20
            else "warm"
        )
    return PromotionDecision(
        patch_id=candidate.patch_id,
        promoted=promoted,
        lifecycle=lifecycle,
        reasons=tuple(reasons),
        rollback_ref=candidate.rollback_ref,
    )


__all__ = [
    "ControlFault", "ControlReceipt", "ExecutionStateEnvelope", "ExperientialPatchCandidate",
    "PromotionDecision", "PromotionEvidence", "SanitizedFailureLesson",
    "localize_control_faults", "promote_experiential_patch",
    "propose_sanitized_failure_lesson",
]
