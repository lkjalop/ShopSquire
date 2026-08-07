from src.app.services.recommendation_core.requirement_compiler import (
    compile_authoritative_requirements,
)
from src.app.services.research_provider_registry import ResearchProvider


def test_advisory_search_snippet_cannot_authorize_hard_requirement():
    result = compile_authoritative_requirements([
        {
            "need_id": "need-ram",
            "subject_span": "digital twin simulation",
            "claim_type": "minimum_requirements",
            "status": "accepted",
            "source_id": "web-search",
            "source_record_id": "snippet-1",
            "observed_at": "2026-08-06T00:00:00Z",
            "confidence": 0.95,
            "attribute_key": "ram_gb",
            "operator": ">=",
            "value": 32,
            "unit": "GB",
            "authority": "advisory",
        }
    ])

    assert result.requirements == ()
    assert result.rejections[0]["reason"] == "source_not_authoritative"


def test_official_typed_claim_compiles_to_registry_backed_predicate():
    result = compile_authoritative_requirements([
        {
            "need_id": "need-ram",
            "subject_span": "digital twin simulation",
            "claim_type": "minimum_requirements",
            "status": "accepted",
            "source_id": "official-vendor-provider",
            "source_record_id": "requirements-v2025",
            "observed_at": "2026-08-06T00:00:00Z",
            "confidence": 0.93,
            "attribute_key": "ram_gb",
            "operator": ">=",
            "value": 32,
            "unit": "GB",
            "authority": "official_requirements",
            "lineage_root": "official-vendor-provider",
        }
    ])

    assert result.rejections == ()
    assert result.requirements[0].attribute_key == "ram_gb"
    assert result.requirements[0].value == 32
    assert result.requirements[0].authority == "accepted_evidence"


def test_provider_registry_uses_the_canonical_approved_document_capability():
    provider = ResearchProvider(
        provider_id="tenant-docs",
        capabilities=("approved_tenant_document",),
        allowed_tenants=("tenant-a",),
        allowed_domains=("docs.example",),
        authority="tenant_approved_repository",
        fetcher_factory=lambda: object(),
    )

    assert provider.capabilities == ("approved_tenant_document",)
