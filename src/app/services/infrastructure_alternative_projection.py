"""Typed, non-authoritative infrastructure-class alternatives for workload decisions.

Catalog substitutes answer "which product?"; this projection answers the earlier architectural
question "where and in what form should the workload run?". It deliberately never selects a class
or grants catalog/commercial authority. Evidence and buyer constraints must do that downstream.
"""

from __future__ import annotations

from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field


InfrastructureClass = Literal[
    "laptop",
    "mobile_workstation",
    "fixed_workstation",
    "server",
    "cloud",
]


class InfrastructureAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    architecture_class: InfrastructureClass
    label: str = Field(min_length=2, max_length=80)
    execution_location: Literal["local", "datacentre", "remote_service"]
    mobility: Literal["portable", "relocatable", "fixed", "not_applicable"]
    scale_mode: Literal["single_user", "shared", "elastic"]
    catalog_relationship: Literal["catalog_product", "sourced_product", "service"]
    tradeoffs_to_verify: list[str] = Field(min_length=2, max_length=6)
    qualification_status: Literal["requires_evidence"] = "requires_evidence"


class InfrastructureAlternativeProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["infrastructure-alternatives-v1"] = "infrastructure-alternatives-v1"
    status: Literal["decision_support"] = "decision_support"
    desired_outcome: str = Field(default="", max_length=240)
    selected_class: None = None
    selection_authority_granted: Literal[False] = False
    commercial_authority_granted: Literal[False] = False
    decision_dimensions: list[str] = Field(min_length=5, max_length=10)
    unresolved_inputs: list[str] = Field(default_factory=list, max_length=8)
    alternatives: list[InfrastructureAlternative] = Field(min_length=5, max_length=5)


_ALTERNATIVES = (
    InfrastructureAlternative(
        architecture_class="laptop",
        label="Laptop",
        execution_location="local",
        mobility="portable",
        scale_mode="single_user",
        catalog_relationship="catalog_product",
        tradeoffs_to_verify=[
            "sustained workload performance", "battery versus plugged-in operation",
            "memory and accelerator capacity", "field portability",
        ],
    ),
    InfrastructureAlternative(
        architecture_class="mobile_workstation",
        label="Mobile workstation",
        execution_location="local",
        mobility="portable",
        scale_mode="single_user",
        catalog_relationship="sourced_product",
        tradeoffs_to_verify=[
            "workload certification", "professional accelerator requirements",
            "serviceability", "weight and power envelope",
        ],
    ),
    InfrastructureAlternative(
        architecture_class="fixed_workstation",
        label="Fixed workstation",
        execution_location="local",
        mobility="fixed",
        scale_mode="single_user",
        catalog_relationship="sourced_product",
        tradeoffs_to_verify=[
            "expandability", "sustained thermals", "local data control",
            "remote access needs",
        ],
    ),
    InfrastructureAlternative(
        architecture_class="server",
        label="Server",
        execution_location="datacentre",
        mobility="fixed",
        scale_mode="shared",
        catalog_relationship="sourced_product",
        tradeoffs_to_verify=[
            "concurrent users", "datacentre and network constraints", "operations ownership",
            "capacity and redundancy",
        ],
    ),
    InfrastructureAlternative(
        architecture_class="cloud",
        label="Cloud",
        execution_location="remote_service",
        mobility="not_applicable",
        scale_mode="elastic",
        catalog_relationship="service",
        tradeoffs_to_verify=[
            "data residency and security", "latency and connectivity", "usage variability",
            "operating versus capital cost",
        ],
    ),
)


def project_infrastructure_alternatives(
    *,
    desired_outcome: str = "",
    unresolved_inputs: Sequence[str] = (),
) -> InfrastructureAlternativeProjection:
    """Return all five architecture classes without silently choosing between them."""
    bounded_unknowns = [
        str(value).strip()[:200]
        for value in unresolved_inputs
        if str(value).strip()
    ][:8]
    return InfrastructureAlternativeProjection(
        desired_outcome=str(desired_outcome or "")[:240],
        decision_dimensions=[
            "mobility",
            "execution_location",
            "offline_operation",
            "data_residency_and_security",
            "concurrent_users",
            "sustained_performance",
            "scalability",
            "ownership_cost_model",
        ],
        unresolved_inputs=bounded_unknowns,
        alternatives=list(_ALTERNATIVES),
    )
