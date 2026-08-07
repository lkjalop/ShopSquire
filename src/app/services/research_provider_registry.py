"""Tenant-scoped registry for bounded external evidence providers.

The recommendation core asks for a capability, never a vendor. This registry is
the policy boundary that maps that capability to configured providers. Selection
does not accept claims or authorize requirements; it only permits a bounded call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal


ProviderCapability = Literal[
    "concept_discovery",
    "official_requirements",
    "standards_regulatory",
    "professional_software_requirements",
    "game_requirements",
    "tenant_approved_documents",
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
    endpoint = str(os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or "").strip()
    tenant_ids = tuple(
        value.strip()
        for value in str(os.getenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST") or "").split(",")
        if value.strip()
    )
    domains = tuple(str(value).strip().lower() for value in allowed_domains if str(value).strip())
    if not endpoint or not tenant_ids or not domains:
        return ResearchProviderRegistry()

    try:
        deadline_ms = int(os.getenv("RESEARCH_LANE_TIMEOUT_MS", "1800") or 1800)
    except (TypeError, ValueError):
        deadline_ms = 1800

    from src.app.adapters.external_research_httpx import HttpxResearchFetcher

    return ResearchProviderRegistry([ResearchProvider(
        provider_id=str(
            os.getenv("EXTERNAL_RESEARCH_PROVIDER_ID") or "allowlisted_http_search"
        ).strip()[:80],
        capabilities=("concept_discovery", "official_requirements"),
        allowed_tenants=tenant_ids,
        allowed_domains=domains,
        authority="official_source_index",
        fetcher_factory=HttpxResearchFetcher,
        deadline_ms=max(100, min(deadline_ms, 30_000)),
    )])
