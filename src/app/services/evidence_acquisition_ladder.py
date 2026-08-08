"""Deterministic zero-cost-first evidence acquisition policy."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceAcquisitionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["evidence-acquisition-v1"] = "evidence-acquisition-v1"
    selected_stage: Literal[
        "sealed_corpus", "evidence_cache", "buyer_upload", "local_discovery",
        "authoritative_origin", "paid_discovery", "request_buyer_input",
    ]
    execution_status: Literal["completed", "ready", "authorization_required", "not_configured"]
    external_authorization_required: bool
    external_calls: int = Field(ge=0)
    paid_calls: int = Field(ge=0)
    next_stage: str | None = None
    reason_codes: list[str]


def choose_evidence_stage(
    *,
    corpus_hit: bool,
    cache_hit: bool,
    accepted_buyer_upload: bool,
    ambiguous_material_gap: bool,
    external_authorized: bool,
    local_discovery_enrolled: bool,
    authoritative_origin_enrolled: bool,
    paid_discovery_allowed: bool = False,
) -> EvidenceAcquisitionDecision:
    if corpus_hit:
        return EvidenceAcquisitionDecision(
            selected_stage="sealed_corpus", execution_status="completed",
            external_authorization_required=False, external_calls=0, paid_calls=0,
            reason_codes=["fresh_sealed_corpus_hit"],
        )
    if cache_hit:
        return EvidenceAcquisitionDecision(
            selected_stage="evidence_cache", execution_status="completed",
            external_authorization_required=False, external_calls=0, paid_calls=0,
            reason_codes=["fresh_evidence_cache_hit"],
        )
    if accepted_buyer_upload:
        return EvidenceAcquisitionDecision(
            selected_stage="buyer_upload", execution_status="completed",
            external_authorization_required=False, external_calls=0, paid_calls=0,
            next_stage="authoritative_origin" if external_authorized else None,
            reason_codes=["accepted_buyer_constraints", "qualification_still_unverified"],
        )
    if not ambiguous_material_gap:
        return EvidenceAcquisitionDecision(
            selected_stage="request_buyer_input", execution_status="ready",
            external_authorization_required=False, external_calls=0, paid_calls=0,
            reason_codes=["no_material_external_evidence_gap"],
        )
    if not external_authorized:
        return EvidenceAcquisitionDecision(
            selected_stage="local_discovery", execution_status="authorization_required",
            external_authorization_required=True, external_calls=0, paid_calls=0,
            reason_codes=["material_gap", "external_authorization_required"],
        )
    if local_discovery_enrolled:
        return EvidenceAcquisitionDecision(
            selected_stage="local_discovery", execution_status="ready",
            external_authorization_required=False, external_calls=0, paid_calls=0,
            next_stage="authoritative_origin",
            reason_codes=["zero_cost_discovery_enrolled"],
        )
    if authoritative_origin_enrolled:
        return EvidenceAcquisitionDecision(
            selected_stage="authoritative_origin", execution_status="ready",
            external_authorization_required=False, external_calls=0, paid_calls=0,
            reason_codes=["known_authoritative_origin"],
        )
    if paid_discovery_allowed:
        return EvidenceAcquisitionDecision(
            selected_stage="paid_discovery", execution_status="ready",
            external_authorization_required=False, external_calls=0, paid_calls=0,
            reason_codes=["free_tiers_exhausted", "paid_discovery_policy_allowed"],
        )
    return EvidenceAcquisitionDecision(
        selected_stage="request_buyer_input", execution_status="not_configured",
        external_authorization_required=False, external_calls=0, paid_calls=0,
        reason_codes=["no_discovery_provider_enrolled", "manual_or_upload_fallback"],
    )


__all__ = ["EvidenceAcquisitionDecision", "choose_evidence_stage"]
