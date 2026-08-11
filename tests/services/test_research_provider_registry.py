from src.app.services.research_provider_registry import (
    ResearchProvider,
    ResearchProviderRegistry,
    configured_registry,
)


class _Fetcher:
    def fetch(self, *_args, **_kwargs):
        return []


def _provider(**overrides):
    values = {
        "provider_id": "official-search",
        "capabilities": ("concept_discovery", "official_requirements"),
        "allowed_tenants": ("tenant-a",),
        "allowed_domains": ("vendor.example",),
        "authority": "official_source_index",
        "fetcher_factory": _Fetcher,
        "deadline_ms": 1200,
    }
    values.update(overrides)
    return ResearchProvider(**values)


def test_registry_selects_by_capability_tenant_consent_and_authority():
    registry = ResearchProviderRegistry([_provider()])

    selected, attempts = registry.select(
        "official_requirements",
        tenant_id="tenant-a",
        buyer_consent=True,
        max_providers=3,
    )

    assert [item.provider_id for item in selected] == ["official-search"]
    assert attempts == [{
        "provider_id": "official-search",
        "status": "selected",
        "capability": "official_requirements",
        "authority": "official_source_index",
        "deadline_ms": 1200,
    }]


def test_registry_fails_closed_for_wrong_tenant_or_missing_consent():
    registry = ResearchProviderRegistry([_provider()])

    selected, attempts = registry.select(
        "official_requirements",
        tenant_id="tenant-b",
        buyer_consent=True,
    )
    assert selected == ()
    assert attempts[0]["status"] == "tenant_not_allowed"

    selected, attempts = registry.select(
        "official_requirements",
        tenant_id="tenant-a",
        buyer_consent=False,
    )
    assert selected == ()
    assert attempts[0]["status"] == "consent_required"


def test_registry_reports_missing_capability_without_a_null_provider():
    registry = ResearchProviderRegistry([_provider()])

    selected, attempts = registry.select(
        "visual_document_evidence",
        tenant_id="tenant-a",
        buyer_consent=True,
    )

    assert selected == ()
    assert attempts == [{
        "provider_id": None,
        "status": "not_configured",
        "capability": "visual_document_evidence",
    }]


def test_configured_registry_separates_discovery_from_official_claim_authority(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_SEARCH_URL", "https://search.example/api?q={query}")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_API_URL", "https://requirements.example/api?q={query}")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST", "docs.vendor.example")
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "tenant-a")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY", "human-reviewer")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_API_KEY", "test-secret")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_PUBLISHER_POLICY_ID", "publisher-policy-v1")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_FRESHNESS_SLA_HOURS", "24")

    registry = configured_registry(allowed_domains=["vendor.example"])
    discovery, _ = registry.select(
        "concept_discovery", tenant_id="tenant-a", buyer_consent=True,
    )
    requirements, _ = registry.select(
        "official_requirements", tenant_id="tenant-a", buyer_consent=True,
    )

    assert [item.provider_id for item in discovery] == ["allowlisted_http_search"]
    assert discovery[0].source_policy is None
    assert [item.provider_id for item in requirements] == ["official_requirements_api"]
    assert requirements[0].allowed_domains == ("docs.vendor.example",)
    assert requirements[0].source_policy["reviewed_by"] == "human-reviewer"
    assert requirements[0].source_policy["freshness_status"] == "not_yet_observed"
    assert requirements[0].freshness_sla_hours == 24
    assert requirements[0].credential_ref == "env:OFFICIAL_REQUIREMENTS_API_KEY"


def test_official_provider_is_not_enrolled_with_incomplete_production_contract(monkeypatch):
    monkeypatch.delenv("EXTERNAL_RESEARCH_SEARCH_URL", raising=False)
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_API_URL", "https://requirements.example/api?q={query}")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST", "docs.vendor.example")
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "tenant-a")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY", "human-reviewer")
    monkeypatch.delenv("OFFICIAL_REQUIREMENTS_API_KEY", raising=False)
    monkeypatch.delenv("OFFICIAL_REQUIREMENTS_PUBLISHER_POLICY_ID", raising=False)
    monkeypatch.delenv("OFFICIAL_REQUIREMENTS_FRESHNESS_SLA_HOURS", raising=False)

    registry = configured_registry(allowed_domains=["vendor.example"])
    selected, attempts = registry.select(
        "official_requirements", tenant_id="tenant-a", buyer_consent=True,
    )

    assert selected == ()
    assert attempts[0]["status"] == "not_configured"


def test_search_proxy_cannot_satisfy_official_requirements_capability(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_SEARCH_URL", "https://search.example/api?q={query}")
    monkeypatch.delenv("OFFICIAL_REQUIREMENTS_API_URL", raising=False)
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "tenant-a")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY", "human-reviewer")

    registry = configured_registry(allowed_domains=["vendor.example"])
    selected, attempts = registry.select(
        "official_requirements", tenant_id="tenant-a", buyer_consent=True,
    )

    assert selected == ()
    assert attempts[0]["status"] == "not_configured"


def test_official_endpoint_without_official_domain_enrollment_is_not_registered(monkeypatch):
    monkeypatch.delenv("EXTERNAL_RESEARCH_SEARCH_URL", raising=False)
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_API_URL", "https://requirements.example/api?q={query}")
    monkeypatch.delenv("OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST", raising=False)
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "tenant-a")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY", "human-reviewer")

    registry = configured_registry(allowed_domains=["reviews.example"])
    selected, attempts = registry.select(
        "official_requirements", tenant_id="tenant-a", buyer_consent=True,
    )

    assert selected == ()
    assert attempts[0]["status"] == "not_configured"
