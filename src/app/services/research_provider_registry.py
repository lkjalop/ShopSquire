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
        limit = max(1, min(int(max_providers), 4))
        candidates = [item for item in self._providers if capability in item.capabilities]
        if not candidates:
            return (), [{
                "provider_id": None,
                "status": "not_configured",
                "capability": capability,
            }]
        selected: list[ResearchProvider] = []
        attempts: list[dict[str, Any]] = []
        for provider in candidates[:limit]:
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
            selected.append(provider)
            attempts.append({
                **base,
                "status": "selected",
                "authority": provider.authority,
                "deadline_ms": provider.deadline_ms,
            })
        return tuple(selected), attempts


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
    source_policy = None
    if reviewed_by:
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
            "freshness_status": "fresh",
        }

    providers: list[ResearchProvider] = []
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
        ))
    if requirements_endpoint and requirements_domains:
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
        ))
    return ResearchProviderRegistry(providers)
