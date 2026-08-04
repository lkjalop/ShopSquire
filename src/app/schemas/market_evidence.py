"""Typed evidence contract for market findings.

Market evidence is advisory input. It can inform a proposal, but it cannot
authorize ranking, pricing, replenishment, or supplier communication.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


EvidenceStatus = Literal["observed", "estimated", "simulated", "insufficient_data", "quarantined"]
EvidenceDirection = Literal["up", "down", "stable", "mixed", "unknown"]
EvidenceAuthority = Literal["advisory", "authoritative"]


class MarketEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_type: str
    tenant_id: str
    subject_type: str
    subject_id: str
    taxonomy_node: str | None = None
    direction: EvidenceDirection = "unknown"
    status: EvidenceStatus
    authority: EvidenceAuthority = "advisory"
    confidence: float = Field(ge=0.0, le=1.0)
    source_system: str | None = None
    source_record_id: str | None = None
    trust_tier: Literal["T1", "T2", "T3", "T4"] | None = None
    licence_id: str | None = None
    licence_url: str | None = None
    licence_terms_hash: str | None = None
    permitted_use: str | None = None
    lineage_root: str | None = None
    provenance_chain: List[str] = Field(default_factory=list)
    observed_at: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    published_at: str | None = None
    available_at: str | None = None
    geography: str | None = None
    measurement_definition: str | None = None
    measurement_scope: str | None = None
    currency: str | None = None
    uom: str | None = None
    release_version: str | None = None
    coverage: Dict[str, Any] = Field(default_factory=dict)
    magnitude_low: float | None = None
    magnitude_high: float | None = None
    propagation_lag_min_days: int | None = Field(default=None, ge=0)
    propagation_lag_max_days: int | None = Field(default=None, ge=0)
    dependency_path_ids: List[str] = Field(default_factory=list)
    supporting_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    alternative_explanations: List[str] = Field(default_factory=list)
    summary: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def provenance_complete(self) -> bool:
        return bool(
            self.source_system
            and self.source_record_id
            and self.lineage_root
            and self.provenance_chain
            and self.observed_at
        )

    @property
    def licensed_provenance_complete(self) -> bool:
        return bool(
            self.provenance_complete
            and self.trust_tier
            and self.licence_id
            and self.licence_url
            and self.licence_terms_hash
            and self.permitted_use
        )
