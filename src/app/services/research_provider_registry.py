"""Tenant-scoped registry for bounded external evidence providers.

The recommendation core asks for a capability, never a vendor. This registry is
the policy boundary that maps that capability to configured providers. Selection
does not accept claims or authorize requirements; it only permits a bounded call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, Mapping


ProviderCapability = Literal[
    "concept_discovery",
    "official_requirements",
    "standards_regulatory",
    "professional_software_requirements",
    "game_requirements",
    "approved_tenant_document",
    "visual_document_evidence",
]
ProviderAuthority = Literal[
    "official_source_index",
    "regulatory_registry",
    "tenant_approved_repository",
]
ProviderBillingClass = Literal["free", "paid", "unknown"]


@dataclass(frozen=True)
class ResearchProvider:
    provider_id: str
    capabilities: tuple[ProviderCapability, ...]
    allowed_tenants: tuple[str, ...]
    allowed_domains: tuple[str, ...]
    authority: ProviderAuthority
    fetcher_factory: Callable[[], Any]
    deadline_ms: int = 1800
    source_policy: Mapping[str, Any] | None = None
    credential_ref: str | None = None
    publisher_policy_id: str | None = None
    freshness_sla_hours: int | None = None
    billing_class: ProviderBillingClass = "unknown"

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("research_provider_id_required")
        if not self.capabilities:
            raise ValueError("research_provider_capability_required")
        if not self.allowed_tenants:
            raise ValueError("research_provider_tenant_allowlist_required")
        if not self.allowed_domains:
            raise ValueError("research_provider_domain_allowlist_required")
        if not 100 <= int(self.deadline_ms) <= 30_000:
            raise ValueError("research_provider_deadline_out_of_bounds")
        if self.freshness_sla_hours is not None and not 1 <= int(self.freshness_sla_hours) <= 8760:
            raise ValueError("research_provider_freshness_sla_out_of_bounds")
        if self.billing_class not in {"free", "paid", "unknown"}:
            raise ValueError("research_provider_billing_class_invalid")


class ResearchProviderRegistry:
    def __init__(self, providers: Iterable[ResearchProvider] = ()) -> None:
        self._providers: list[ResearchProvider] = []
        for provider in providers:
            self.register(provider)

    def register(self, provider: ResearchProvider) -> None:
        if any(item.provider_id == provider.provider_id for item in self._providers):
            raise ValueError(f"duplicate research provider: {provider.provider_id}")
        self._providers.append(provider)

    def select(
        self,
        capability: ProviderCapability,
        *,
        tenant_id: str,
        buyer_consent: bool,
        max_providers: int = 3,
    ) -> tuple[tuple[ResearchProvider, ...], list[dict[str, Any]]]:
        selected, attempts, _receipt = self.select_with_receipt(
            capability, tenant_id=tenant_id, buyer_consent=buyer_consent,
            max_providers=max_providers,
        )
        return selected, attempts

    def select_with_receipt(
        self,
        capability: ProviderCapability,
        *,
        tenant_id: str,
        buyer_consent: bool,
        max_providers: int = 3,
    ):
        """Select through the cross-domain capability fabric and retain legacy attempts."""
        from src.app.services.tool_capability_selector import (
            ToolDeployment, ToolHealth, ToolPolicy, ToolRequirement,
            select_tool_deployments,
        )

        capability_map = {
            "concept_discovery": "discover_authoritative_origin",
            "official_requirements": "authoritative_software_requirements",
            "standards_regulatory": "authoritative_software_requirements",
            "professional_software_requirements": "authoritative_software_requirements",
            "game_requirements": "authoritative_software_requirements",
            "approved_tenant_document": "buyer_document_extraction",
            "visual_document_evidence": "buyer_document_extraction",
        }
        limit = max(1, min(int(max_providers), 4))
        candidates = [item for item in self._providers if capability in item.capabilities]
        if not candidates:
            return (), [{
                "provider_id": None,
                "status": "not_configured",
                "capability": capability,
            }], None
        attempts: list[dict[str, Any]] = []
        eligible: list[ResearchProvider] = []
        for provider in candidates:
            base = {
                "provider_id": provider.provider_id,
                "capability": capability,
            }
            if not buyer_consent:
                attempts.append({**base, "status": "consent_required"})
                continue
            if str(tenant_id or "").strip() not in provider.allowed_tenants:
                attempts.append({**base, "status": "tenant_not_allowed"})
                continue
            eligible.append(provider)
        deployments = tuple(ToolDeployment(
            deployment_id=provider.provider_id,
            capabilities=(capability_map[capability],),
            policy=ToolPolicy(
                allowed_tenants=provider.allowed_tenants,
                allowed_claim_classes=tuple(
                    str(value) for value in (provider.source_policy or {}).get(
                        "allowed_claim_types", ()
                    )
                ),
                authority_score={
                    "regulatory_registry": 100,
                    "official_source_index": 90,
                    "tenant_approved_repository": 80,
                }[provider.authority],
                freshness_state=(
                    "fresh" if (provider.source_policy or {}).get("freshness_status") == "fresh"
                    else "stale" if (provider.source_policy or {}).get("freshness_status") == "stale"
                    else "unknown"
                ),
                side_effect_class="external_read",
                cost_units=1 if provider.billing_class == "paid" else 0,
            ),
            health=ToolHealth(status="unknown"),
        ) for provider in eligible)
        requirement = ToolRequirement(
            capability=capability_map[capability], tenant_id=tenant_id,
            max_latency_ms=max((row.deadline_ms for row in eligible), default=1800),
            max_cost_units=1000, permitted_side_effects=("external_read",),
        )
        receipt = select_tool_deployments(
            requirement, deployments, max_results=limit,
        )
        by_id = {row.provider_id: row for row in eligible}
        selected = tuple(by_id[row] for row in receipt.selected_deployment_ids)
        selected_ids = set(receipt.selected_deployment_ids)
        for provider in eligible:
            base = {"provider_id": provider.provider_id, "capability": capability}
            if provider.provider_id in selected_ids:
                attempts.append({
                    **base, "status": "selected", "authority": provider.authority,
                    "deadline_ms": provider.deadline_ms,
                })
            else:
                candidate = next(
                    row for row in receipt.candidates
                    if row.deployment_id == provider.provider_id
                )
                attempts.append({
                    **base, "status": "policy_rejected",
                    "reasons": list(candidate.reasons),
                })
        return selected, attempts, receipt


def configured_registry(*, allowed_domains: Iterable[str]) -> ResearchProviderRegistry:
    """Build the operator-configured registry; incomplete config remains empty."""
    search_endpoint = str(os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or "").strip()
    requirements_endpoint = str(os.getenv("OFFICIAL_REQUIREMENTS_API_URL") or "").strip()
    tenant_ids = tuple(
        value.strip()
        for value in str(os.getenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST") or "").split(",")
        if value.strip()
    )
    domains = tuple(str(value).strip().lower() for value in allowed_domains if str(value).strip())
    requirements_domains = tuple(
        value.strip().lower()
        for value in str(os.getenv("OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST") or "").split(",")
        if value.strip()
    )
    if not (search_endpoint or requirements_endpoint) or not tenant_ids or not domains:
        return ResearchProviderRegistry()

    try:
        deadline_ms = int(os.getenv("RESEARCH_LANE_TIMEOUT_MS", "1800") or 1800)
    except (TypeError, ValueError):
        deadline_ms = 1800

    from src.app.adapters.external_research_httpx import HttpxResearchFetcher
    from src.app.adapters.official_requirements_httpx import OfficialRequirementsHttpFetcher

    reviewed_by = str(os.getenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY") or "").strip()
    requirements_credential = str(os.getenv("OFFICIAL_REQUIREMENTS_API_KEY") or "").strip()
    publisher_policy_id = str(
        os.getenv("OFFICIAL_REQUIREMENTS_PUBLISHER_POLICY_ID") or ""
    ).strip()
    try:
        freshness_sla_hours = int(
            os.getenv("OFFICIAL_REQUIREMENTS_FRESHNESS_SLA_HOURS", "0") or 0
        )
    except (TypeError, ValueError):
        freshness_sla_hours = 0
    source_policy = None
    if reviewed_by and publisher_policy_id and freshness_sla_hours > 0:
        source_policy = {
            "policy_version": "semantic-source-v1",
            "review_status": "approved",
            "reviewer_type": "independent_human",
            "reviewed_by": reviewed_by[:120],
            "licence": str(
                os.getenv("EXTERNAL_RESEARCH_SOURCE_LICENCE") or "operator-authorized"
            )[:120],
            "trust_tier": "authoritative",
            "allowed_claim_types": [
                "concept_identity", "minimum_requirements", "recommended_requirements",
                "target_requirements", "compatibility", "certification",
            ],
            # Enrollment declares the SLA, not an observation. A fetched source revision must
            # still supply observed_at before downstream policy can call it fresh.
            "freshness_status": "not_yet_observed",
            "freshness_sla_hours": min(freshness_sla_hours, 8760),
            "publisher_policy_id": publisher_policy_id[:160],
        }

    providers: list[ResearchProvider] = []
    discovery_billing = str(
        os.getenv("EXTERNAL_RESEARCH_PROVIDER_BILLING_CLASS") or "unknown"
    ).strip().lower()
    requirements_billing = str(
        os.getenv("OFFICIAL_REQUIREMENTS_PROVIDER_BILLING_CLASS") or "unknown"
    ).strip().lower()
    if discovery_billing not in {"free", "paid", "unknown"}:
        discovery_billing = "unknown"
    if requirements_billing not in {"free", "paid", "unknown"}:
        requirements_billing = "unknown"
    if search_endpoint:
        providers.append(ResearchProvider(
            provider_id=str(
                os.getenv("EXTERNAL_RESEARCH_PROVIDER_ID") or "allowlisted_http_search"
            ).strip()[:80],
            capabilities=("concept_discovery",),
            allowed_tenants=tenant_ids,
            allowed_domains=domains,
            authority="official_source_index",
            fetcher_factory=HttpxResearchFetcher,
            deadline_ms=max(100, min(deadline_ms, 30_000)),
            source_policy=None,
            billing_class=discovery_billing,
        ))
    if (
        requirements_endpoint
        and requirements_domains
        and requirements_credential
        and source_policy is not None
    ):
        providers.append(ResearchProvider(
            provider_id=str(
                os.getenv("OFFICIAL_REQUIREMENTS_PROVIDER_ID")
                or "official_requirements_api"
            ).strip()[:80],
            capabilities=("official_requirements", "professional_software_requirements"),
            allowed_tenants=tenant_ids,
            allowed_domains=requirements_domains,
            authority="official_source_index",
            fetcher_factory=OfficialRequirementsHttpFetcher,
            deadline_ms=max(100, min(deadline_ms, 30_000)),
            source_policy=source_policy,
            credential_ref="env:OFFICIAL_REQUIREMENTS_API_KEY",
            publisher_policy_id=publisher_policy_id[:160],
            freshness_sla_hours=min(freshness_sla_hours, 8760),
            billing_class=requirements_billing,
        ))
    return ResearchProviderRegistry(providers)
