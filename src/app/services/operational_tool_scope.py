"""Adapters from operational read seams into the provider-neutral ToolScope contract."""
from __future__ import annotations

from src.app.services.tool_capability_selector import (
    ToolCapability,
    ToolDeployment,
    ToolHealth,
    ToolPolicy,
    ToolRequirement,
    ToolSelectionReceipt,
    select_tool_deployments,
)


def operational_read_receipt(
    *, capability: ToolCapability, tenant_id: str, deployment_id: str,
    enabled: bool, freshness_state: str = "unknown", health_status: str = "unknown",
    authority_score: int = 70, side_effect_class: str = "none",
    rolling_latency_ms: int | None = None,
) -> ToolSelectionReceipt:
    """Select one enrolled operational read without granting write authority."""
    deployment = ToolDeployment(
        deployment_id=deployment_id,
        capabilities=(capability,), enabled=enabled,
        policy=ToolPolicy(
            allowed_tenants=(tenant_id,), authority_score=authority_score,
            freshness_state=freshness_state,
            side_effect_class=side_effect_class, cost_units=0,
        ),
        health=ToolHealth(
            status=health_status, rolling_latency_ms=rolling_latency_ms,
        ),
    )
    return select_tool_deployments(
        ToolRequirement(
            capability=capability, tenant_id=tenant_id, max_cost_units=0,
            permitted_side_effects=("none", "external_read"),
        ),
        (deployment,), max_results=1,
    )


__all__ = ["operational_read_receipt"]
