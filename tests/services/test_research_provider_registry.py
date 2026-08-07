from src.app.services.research_provider_registry import (
    ResearchProvider,
    ResearchProviderRegistry,
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
