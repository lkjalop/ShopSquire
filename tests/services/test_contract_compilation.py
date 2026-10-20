from datetime import datetime, timezone

import pytest

from src.app.services.requirement_contract import ContractContext, RequirementContract
from src.app.services.recommendation_core.requirement_compiler import compile_authoritative_requirements
from src.app.services.recommendation_core.requirement_scope import resolve_requirement_scope

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def fixture(attribute="ram_gb"):
    context = ContractContext(subject="Previously unseen application", version="7", platform="A", workload="B")
    contract = RequirementContract(id="test", context=context, obligations=[dict(
        id="capacity", attribute=attribute, tier="minimum", source_ids=["publisher"], max_age_hours=24)])
    scope = resolve_requirement_scope(tenant_id="test", profile_id="electronics", product_type="el-6-6",
                                      relationship="RUN_SUBJECT_ON_PRODUCT")
    claim = dict(status="accepted", authority="official_requirements", claim_id="duplicate",
                 attribute_key=attribute, value=16, operator=">=", unit="GB", requirement_class="minimum",
                 source_id="publisher", source_record_id="page", lineage_root="publisher", confidence=1,
                 source_revision="hash", source_excerpt="16 GB", observed_at=NOW.isoformat(),
                 applicability=context.model_dump(), artefact_name=context.subject, artefact_version=context.version)
    return contract, context, scope, claim


def test_contract_coverage_passes_through_actual_registry_compiler():
    contract, context, scope, claim = fixture()
    result = compile_authoritative_requirements([claim], scope=scope, contract=contract, contract_context=context, now=NOW)
    assert len(result.requirements) == 1
    assert result.contract_coverage["compiled_complete"]
    assert result.contract_coverage["commerce_authority"] == "none"


def test_compiled_provider_projection_retains_contract_coverage_and_original_freshness():
    from src.app.services.structured_requirement_claims import project_structured_requirement_claims
    from src.app.services.requirement_contract import assess_contract_coverage
    contract, context, scope, claim = fixture()
    result = compile_authoritative_requirements([claim], scope=scope, contract=contract,
                                                contract_context=context, now=NOW)
    projected = project_structured_requirement_claims({'evidence': [{
        'status': 'resolved', 'provider_id': 'aggregator',
        'retrieved_at': '2026-09-27T00:00:00+00:00',
        'compiled_requirements': [r.model_dump(mode='json') for r in result.requirements],
    }]})
    assert projected[0]['observed_at'] == claim['observed_at']
    assert projected[0]['source_id'] == 'publisher'
    assert projected[0]['applicability'] == context.model_dump()
    assert assess_contract_coverage(contract, context=context, claims=projected, now=NOW)['coverage_complete']


@pytest.mark.parametrize("change", [{"revoked_at": NOW.isoformat()}, {"artefact_version": "8"},
                                     {"applicability": None}, {"status": "held"}, {"observed_at": "2020-01-01T00:00:00Z"}])
def test_coverage_failures_cannot_compile(change):
    contract, context, scope, claim = fixture()
    result = compile_authoritative_requirements([{**claim, **change}], scope=scope, contract=contract,
                                                contract_context=context, now=NOW)
    assert not result.requirements
    assert not result.contract_coverage["compiled_complete"]


def test_covered_unregistered_attribute_is_not_an_executable_requirement():
    contract, context, scope, claim = fixture("unsupported_capacity")
    result = compile_authoritative_requirements([claim], scope=scope, contract=contract, contract_context=context, now=NOW)
    assert result.contract_coverage["coverage_complete"]
    assert not result.contract_coverage["compiled_complete"]
    assert not result.requirements
    assert result.rejections[0]["reason"] == "attribute_not_applicable"


def test_missing_context_or_scope_cannot_be_supplied_by_source_fields():
    contract, context, scope, claim = fixture()
    for args in (dict(scope=scope), dict(contract_context=context)):
        result = compile_authoritative_requirements([{**claim, "contract_context": context.model_dump()}],
                                                    contract=contract, now=NOW, **args)
        assert not result.requirements
        assert not result.contract_coverage["compiled_complete"]


def test_extra_claim_with_duplicate_external_id_cannot_bypass_contract():
    contract, context, scope, claim = fixture()
    extra = {**claim, "attribute_key": "gpu_vram_gb"}
    result = compile_authoritative_requirements([claim, extra], scope=scope, contract=contract, contract_context=context, now=NOW)
    assert [r.attribute_key for r in result.requirements] == ["ram_gb"]
    assert result.rejections[0]["reason"] == "claim_outside_contract"


def test_one_unsupported_required_obligation_quarantines_the_compilable_subset():
    contract, context, scope, claim = fixture()
    raw = contract.model_dump()
    raw["obligations"] = list(raw["obligations"])
    raw["obligations"].append({**raw["obligations"][0], "id": "unknown", "attribute": "unknown_attribute"})
    contract = RequirementContract.model_validate(raw)
    result = compile_authoritative_requirements([claim, {**claim, "attribute_key": "unknown_attribute"}],
                                                scope=scope, contract=contract, contract_context=context, now=NOW)
    assert result.contract_coverage["coverage_complete"]
    assert not result.contract_coverage["compiled_complete"]
    assert not result.requirements
    assert {r["reason"] for r in result.rejections} == {"attribute_not_applicable", "contract_compilation_incomplete"}
