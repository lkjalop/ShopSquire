from src.app.services.recommendation_core.requirement_compiler import (
    compile_authoritative_requirements as _compile,
)
from src.app.services.recommendation_core.requirement_scope import resolve_requirement_scope
from src.app.services.research_provider_registry import ResearchProvider
import pytest


def compile_authoritative_requirements(claims):
    """Unit fixture: these pre-existing compiler cases exercise computer fit."""
    return _compile(claims, scope=resolve_requirement_scope(
        tenant_id="test", profile_id="electronics", product_type="el-6-6",
        relationship="RUN_SUBJECT_ON_PRODUCT",
    ))


def _claim(**changes):
    return {
        "status": "accepted", "authority": "official_requirements",
        "source_id": "test-publisher", "source_record_id": "requirements-page",
        "lineage_root": "test-publisher", "observed_at": "2026-09-07T00:00:00Z",
        "confidence": 1, "attribute_key": "ram_gb", "operator": ">=",
        "value": 16, "unit": "GB", **changes,
    }


def test_compiled_equality_executes_in_fit_engine():
    from src.app.services.attribute_registry import evaluate_requirements
    result = compile_authoritative_requirements([_claim(operator="=")])
    assert not result.rejections
    item = result.requirements[0]
    requirements = {item.attribute_key: (item.operator, item.value)}
    assert evaluate_requirements({"ram_gb": 16}, requirements)["overall"] == "meets"
    assert evaluate_requirements({"ram_gb": 32}, requirements)["overall"] == "fails"
    assert evaluate_requirements({}, requirements)["overall"] == "unknown"


def test_text_substring_cannot_authorize_hardware_fit():
    result = compile_authoritative_requirements([
        _claim(attribute_key="cpu_model", operator="contains", value="Intel", unit=None),
    ])
    assert not result.requirements
    assert result.rejections[0]["reason"] == "operator_not_authorized"


def test_cited_exact_hardware_alternatives_are_not_a_performance_translation():
    from src.app.services.attribute_registry import evaluate_requirements
    result = compile_authoritative_requirements([_claim(
        attribute_key="gpu_model", operator="in", unit=None,
        value=["Example GPU A", "Example GPU B"],
        source_excerpt="Graphics: Example GPU A or Example GPU B",
        value_spans=[[10, 23], [27, 40]],
    )])
    assert not result.rejections
    item = result.requirements[0]
    requirements = {item.attribute_key: (item.operator, item.value)}
    assert evaluate_requirements({"gpu_model": "Example GPU A"}, requirements)["overall"] == "meets"
    assert evaluate_requirements({"gpu_model": "Example GPU A Mobile"}, requirements)["overall"] == "fails"
    assert evaluate_requirements({}, requirements)["overall"] == "unknown"


def test_uncited_hardware_alternative_is_rejected():
    result = compile_authoritative_requirements([_claim(
        attribute_key="cpu_model", operator="in", unit=None,
        value=["Invented CPU"], source_excerpt="Example CPU", value_spans=[[0, 11]],
    )])
    assert not result.requirements
    assert result.rejections[0]["reason"] == "alternative_span_invalid"


@pytest.mark.parametrize("changes,reason", [
    ({"unit": "mg"}, "unit_not_registry_valid"),
    ({"operator": "contains"}, "operator_not_authorized"),
    ({"value": float("nan")}, "value_not_registry_valid"),
    ({"confidence": float("nan")}, "confidence_below_policy"),
])
def test_compilation_rejects_invalid_typed_boundaries(changes, reason):
    result = compile_authoritative_requirements([_claim(**changes)])
    assert not result.requirements
    assert result.rejections[0]["reason"] == reason
    assert result.rejections[0]["attribute_key"] == "ram_gb"


def test_compilation_converts_separate_source_unit():
    result = compile_authoritative_requirements([_claim(value=16384, unit="MB")])
    assert not result.rejections
    assert result.requirements[0].value == 16
    assert result.requirements[0].unit == "GB"


def test_source_record_is_not_predicate_identity():
    rows = [_claim(), _claim(attribute_key="gpu_vram_gb", value=6)]
    result = compile_authoritative_requirements(rows)
    ids = [item.source_claim_ids[0] for item in result.requirements]
    assert len(set(ids)) == 2
    repeated = compile_authoritative_requirements(list(reversed(rows)))
    assert set(ids) == {item.source_claim_ids[0] for item in repeated.requirements}


def test_case_document_acceptance_is_not_publisher_verification():
    result = compile_authoritative_requirements([_claim(authority="approved_tenant_document")])
    assert result.requirements[0].verification_status == "unverified"


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
            "artefact_name": "USD Composer",
            "artefact_version": "2026.2",
            "requirement_class": "recommended",
            "scope_caveat": "Good tier, not a performance guarantee",
            "source_revision": "2026-07-27",
            "freshness_status": "fresh",
        }
    ])

    assert result.rejections == ()
    assert result.requirements[0].attribute_key == "ram_gb"
    assert result.requirements[0].value == 32
    assert result.requirements[0].authority == "accepted_evidence"
    assert result.requirements[0].artefact_name == "USD Composer"
    assert result.requirements[0].artefact_version == "2026.2"
    assert result.requirements[0].requirement_class == "recommended"
    assert result.requirements[0].freshness_status == "fresh"


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
