"""Typed executive-metric evidence and role projections."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


MetricStatus = Literal["observed", "estimated", "simulated", "insufficient_data", "unavailable"]
MetricVisibility = Literal["buyer", "operator", "auditor"]


class MetricEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    tenant_id: str
    subject_type: str
    subject_id: str
    value: float | int | None = None
    unit: str | None = None
    currency: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    as_of: datetime
    status: MetricStatus
    confidence: float = Field(ge=0.0, le=1.0)
    coverage: float = Field(ge=0.0, le=1.0)
    source_count: int = Field(ge=0)
    source_records: List[str] = Field(default_factory=list)
    provenance_chain: List[str] = Field(default_factory=list)
    definition_version: str
    visibility: MetricVisibility
    reason: str | None = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BuyerMetricProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    metrics: List[MetricEvidence] = Field(default_factory=list)
    data_quality: Dict[str, Any] = Field(default_factory=dict)


class OperatorMetricProjection(BuyerMetricProjection):
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    estimates: Dict[str, Any] = Field(default_factory=dict)


class AuditorMetricProjection(OperatorMetricProjection):
    quarantined_evidence_count: int = 0
    policy_decisions: List[Dict[str, Any]] = Field(default_factory=list)
