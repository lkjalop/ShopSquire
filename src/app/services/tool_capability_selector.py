"""Policy-first capability selection across evidence and commerce tool classes.

Callers request a capability. They never request a vendor or a side effect.
Selection is deterministic and emits a complete receipt for Decision Trace.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCapability(StrEnum):
    AUTHORITATIVE_SOFTWARE_REQUIREMENTS = "authoritative_software_requirements"
    OEM_PRODUCT_SPECIFICATION = "oem_product_specification"
    CATALOG_LOOKUP = "catalog_lookup"
    INVENTORY_AVAILABILITY = "inventory_availability"
    SUPPLIER_OFFER_READ = "supplier_offer_read"
    CARRIER_SERVICE_READ = "carrier_service_read"
    FORECAST_OBSERVATION_READ = "forecast_observation_read"
    BUYER_DOCUMENT_EXTRACTION = "buyer_document_extraction"
    DISCOVER_AUTHORITATIVE_ORIGIN = "discover_authoritative_origin"
    SEND_RFQ = "send_rfq"
    CHANGE_CART = "change_cart"


SideEffectClass = Literal["none", "external_read", "draft_only", "commercial_write"]


class ToolRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: ToolCapability
    tenant_id: str = Field(min_length=1, max_length=200)
    required_claim_class: str | None = Field(default=None, max_length=120)
    minimum_authority: int = Field(default=0, ge=0, le=100)
    max_latency_ms: int = Field(default=3000, ge=50, le=120_000)
    max_cost_units: int = Field(default=0, ge=0, le=1000)
    permitted_side_effects: tuple[SideEffectClass, ...] = ("none", "external_read")


class ToolHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["healthy", "degraded", "unhealthy", "unknown"]
    rolling_latency_ms: int | None = Field(default=None, ge=0, le=120_000)
    failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    observed_at: str | None = None


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_tenants: tuple[str, ...] = Field(min_length=1)
    allowed_claim_classes: tuple[str, ...] = ()
    authority_score: int = Field(default=0, ge=0, le=100)
    freshness_state: Literal["fresh", "stale", "unknown", "not_applicable"] = "unknown"
    side_effect_class: SideEffectClass = "none"
    cost_units: int = Field(default=0, ge=0, le=1000)


class ToolDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deployment_id: str = Field(min_length=1, max_length=160)
    capabilities: tuple[ToolCapability, ...] = Field(min_length=1)
    policy: ToolPolicy
    health: ToolHealth
    enabled: bool = True


class ToolSelectionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deployment_id: str
    status: Literal["eligible", "rejected"]
    score: int | None = None
    reasons: tuple[str, ...] = ()


class ToolSelectionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: ToolCapability
    selected_deployment_ids: tuple[str, ...]
    candidates: tuple[ToolSelectionCandidate, ...]
    outcome: Literal["selected", "no_eligible_deployment"]
    commercial_authority_granted: Literal[False] = False


def _score(requirement: ToolRequirement, deployment: ToolDeployment) -> tuple[int | None, tuple[str, ...]]:
    reasons: list[str] = []
    policy, health = deployment.policy, deployment.health
    if not deployment.enabled:
        reasons.append("deployment_disabled")
    if requirement.capability not in deployment.capabilities:
        reasons.append("capability_missing")
    if requirement.tenant_id not in policy.allowed_tenants:
        reasons.append("tenant_not_allowed")
    if (
        requirement.required_claim_class
        and requirement.required_claim_class not in policy.allowed_claim_classes
    ):
        reasons.append("claim_class_not_allowed")
    if policy.authority_score < requirement.minimum_authority:
        reasons.append("authority_below_minimum")
    if policy.side_effect_class not in requirement.permitted_side_effects:
        reasons.append("side_effect_not_permitted")
    if policy.cost_units > requirement.max_cost_units:
        reasons.append("cost_allowance_exceeded")
    if health.status == "unhealthy":
        reasons.append("deployment_unhealthy")
    if health.rolling_latency_ms is not None and health.rolling_latency_ms > requirement.max_latency_ms:
        reasons.append("latency_deadline_exceeded")
    if reasons:
        return None, tuple(reasons)
    score = 1000 + policy.authority_score * 5
    score += {"fresh": 120, "not_applicable": 60, "unknown": 0, "stale": -100}[policy.freshness_state]
    score += {"healthy": 100, "degraded": -50, "unknown": -20, "unhealthy": -1000}[health.status]
    score -= int((health.rolling_latency_ms or requirement.max_latency_ms) / 25)
    score -= policy.cost_units * 20
    score -= {"none": 0, "external_read": 10, "draft_only": 100, "commercial_write": 1000}[
        policy.side_effect_class
    ]
    return score, ()


def select_tool_deployments(
    requirement: ToolRequirement,
    deployments: tuple[ToolDeployment, ...] | list[ToolDeployment],
    *,
    max_results: int = 3,
) -> ToolSelectionReceipt:
    evaluated: list[ToolSelectionCandidate] = []
    for deployment in deployments:
        score, reasons = _score(requirement, deployment)
        evaluated.append(ToolSelectionCandidate(
            deployment_id=deployment.deployment_id,
            status="eligible" if score is not None else "rejected",
            score=score, reasons=reasons,
        ))
    evaluated.sort(key=lambda row: (
        row.status != "eligible", -(row.score or -1), row.deployment_id,
    ))
    limit = max(1, min(int(max_results), 8))
    selected = tuple(row.deployment_id for row in evaluated if row.status == "eligible")[:limit]
    return ToolSelectionReceipt(
        capability=requirement.capability,
        selected_deployment_ids=selected,
        candidates=tuple(evaluated),
        outcome="selected" if selected else "no_eligible_deployment",
    )


__all__ = [
    "ToolCapability", "ToolDeployment", "ToolHealth", "ToolPolicy", "ToolRequirement",
    "ToolSelectionReceipt", "select_tool_deployments",
]
