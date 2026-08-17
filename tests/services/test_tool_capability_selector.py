import pytest
from pydantic import ValidationError

from src.app.services.tool_capability_selector import (
    ToolDeployment,
    ToolHealth,
    ToolPolicy,
    ToolRequirement,
    select_tool_deployments,
)


def _deployment(name, *, capability="authoritative_software_requirements", authority=80,
                latency=200, cost=0, effect="external_read", health="healthy"):
    return ToolDeployment(
        deployment_id=name, capabilities=(capability,),
        policy=ToolPolicy(
            allowed_tenants=("portfolio",), allowed_claim_classes=("minimum_requirements",),
            authority_score=authority, freshness_state="fresh",
            side_effect_class=effect, cost_units=cost,
        ),
        health=ToolHealth(status=health, rolling_latency_ms=latency),
    )


def test_requirement_cannot_name_or_smuggle_a_provider():
    with pytest.raises(ValidationError):
        ToolRequirement(
            capability="authoritative_software_requirements", tenant_id="portfolio",
            provider_id="search-vendor-a",
        )


def test_selector_prefers_authority_health_latency_and_zero_cost_deterministically():
    requirement = ToolRequirement(
        capability="authoritative_software_requirements", tenant_id="portfolio",
        required_claim_class="minimum_requirements", minimum_authority=60,
        max_latency_ms=2000, max_cost_units=0,
    )
    receipt = select_tool_deployments(requirement, [
        _deployment("slow", authority=80, latency=1500),
        _deployment("best", authority=90, latency=100),
        _deployment("paid", authority=100, latency=50, cost=2),
        _deployment("unhealthy", authority=100, latency=50, health="unhealthy"),
    ])
    assert receipt.selected_deployment_ids[:2] == ("best", "slow")
    rejected = {row.deployment_id: row.reasons for row in receipt.candidates if row.status == "rejected"}
    assert rejected["paid"] == ("cost_allowance_exceeded",)
    assert rejected["unhealthy"] == ("deployment_unhealthy",)
    assert receipt.commercial_authority_granted is False


def test_read_stage_cannot_escalate_to_rfq_or_cart_write():
    requirement = ToolRequirement(
        capability="send_rfq", tenant_id="portfolio", max_cost_units=10,
        permitted_side_effects=("none", "external_read"),
    )
    receipt = select_tool_deployments(requirement, [
        _deployment("rfq-sender", capability="send_rfq", effect="commercial_write"),
    ])
    assert receipt.outcome == "no_eligible_deployment"
    assert receipt.candidates[0].reasons == ("side_effect_not_permitted",)


def test_explicit_wildcard_policy_allows_any_tenant():
    deployment = _deployment("local-catalog", capability="catalog_lookup", effect="none")
    deployment = deployment.model_copy(update={
        "policy": deployment.policy.model_copy(update={"allowed_tenants": ("*",)}),
    })
    receipt = select_tool_deployments(
        ToolRequirement(capability="catalog_lookup", tenant_id="tenant-any"),
        [deployment],
    )
    assert receipt.selected_deployment_ids == ("local-catalog",)
