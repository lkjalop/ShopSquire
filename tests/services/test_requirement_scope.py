import pytest
import json

from src.app.services.recommendation_core.requirement_compiler import compile_authoritative_requirements
from src.app.services.recommendation_core.requirement_scope import resolve_requirement_scope


def claim(key="ram_gb", value=16):
    return dict(status="accepted", authority="official_requirements", source_id="publisher",
                source_record_id="page", lineage_root="publisher", observed_at="2026-09-07",
                confidence=1, attribute_key=key, operator=">=", value=value)


def scope(**changes):
    return resolve_requirement_scope(**{
        "tenant_id": "tenant-a", "profile_id": "electronics", "product_type": "el-6-6",
        "relationship": "RUN_SUBJECT_ON_PRODUCT", **changes,
    })


def test_manifest_revision_covers_derivation_policy(monkeypatch, tmp_path):
    from src.app.services import attribute_registry as registry
    raw = json.loads((registry._DATA_DIR / 'electronics.json').read_text(encoding='utf-8'))
    definitions = registry.load_defs('electronics')
    monkeypatch.setattr(registry, '_DATA_DIR', tmp_path)
    monkeypatch.setattr(registry, 'load_defs', lambda _: definitions)
    path = tmp_path / 'electronics.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    before = scope()
    raw['derivations'] = [{'target':'gpu_vram_gb', 'set':0, 'when':{'gpu_discrete':False}, 'only_if_missing':True}]
    path.write_text(json.dumps(raw), encoding='utf-8')
    # Ensure this is a different rule payload even if the source already had it.
    raw['derivations'][0]['set'] = 1
    path.write_text(json.dumps(raw), encoding='utf-8')
    after = scope()
    assert before.manifest_revision != after.manifest_revision


def test_discovery_retries_preserve_explicit_product_scope(monkeypatch):
    from src.app.services.recommendation_core import workload_grounding as W
    received = []
    def resolve(entities, *, consent, product_type):
        received.append(product_type)
        return {"requirements": {}, "evidence": [], "live_allowed": False}
    monkeypatch.setattr(W, "resolve_named_workloads", resolve)
    W.resolve_unresolved_concepts(["Unseen"], workload_kind_hints=[], consent=False,
                                  product_type="el-6-2")
    W.resolve_canonical_workload_identity(
        {"status": "resolved", "identity": {"canonical_title": "Unseen"}},
        workload_kind_hints=["software"], consent=False, product_type="el-6-2",
    )
    assert received == ["el-6-2", "el-6-2", "el-6-2"]


def test_scope_is_required_not_inferred_from_installed_packs():
    result = compile_authoritative_requirements([claim()])
    assert not result.requirements
    assert result.rejections[0]["reason"] == "compilation_scope_unresolved"


@pytest.mark.parametrize("product_type", ["el-6-6", "el-6-2", "not-a-product"])
def test_provider_adapter_uses_requested_scope_without_broad_fallback(product_type):
    from src.app.services.recommendation_core.workload_grounding import compile_workload_evidence_requirements
    result = compile_workload_evidence_requirements({
        "source": "publisher", "app_id": "page", "confidence": 1,
        "retrieved_at": "2026-09-07", "minimum": {"ram_gb": 16},
    }, kind="software", name="Unseen subject", product_type=product_type)
    if product_type == "not-a-product":
        assert not result.requirements
        assert result.rejections[0]["reason"] == "compilation_scope_unresolved"
    else:
        assert result.requirements
        assert result.requirements[0].compilation_scope.product_type == product_type


def test_electronics_scope_rejects_pharmacy_attribute():
    result = compile_authoritative_requirements([claim("strength_mg", 10)], scope=scope())
    assert not result.requirements
    assert result.rejections[0]["reason"] == "attribute_not_applicable"


def test_scope_is_carried_by_compiled_claim():
    pinned = scope()
    result = compile_authoritative_requirements([claim()], scope=pinned)
    assert result.requirements[0].compilation_scope == pinned
    assert pinned.tenant_id == "tenant-a"
    assert pinned.product_type == "el-6-6"
    assert len(pinned.manifest_revision) == 64


@pytest.mark.parametrize("changes", [
    {"profile_id": "pharmacy"}, {"profile_id": "does-not-exist"},
    {"product_type": "fr-12-2"}, {"relationship": "UNRESOLVED"},
    {"tenant_id": ""},
])
def test_unsupported_scope_has_no_electronics_fallback(changes):
    assert scope(**changes) is None


def test_storage_fit_is_explicit_not_every_variant_axis():
    result = compile_authoritative_requirements([claim("storage_gb", 40)], scope=scope())
    assert [r.attribute_key for r in result.requirements] == ["storage_gb"]


def test_stale_manifest_revision_cannot_compile():
    stale = scope().model_copy(update={"manifest_revision": "0" * 64})
    result = compile_authoritative_requirements([claim()], scope=stale)
    assert not result.requirements
    assert result.rejections[0]["reason"] == "compilation_scope_stale"


def test_changed_definition_invalidates_pinned_scope(monkeypatch):
    from dataclasses import replace
    from src.app.services import attribute_registry
    pinned = scope()
    definitions = dict(attribute_registry.load_defs("electronics"))
    definitions["ram_gb"] = replace(definitions["ram_gb"], bounds=(1, 128))
    monkeypatch.setattr(attribute_registry, "load_defs", lambda _profile: definitions)
    result = compile_authoritative_requirements([claim()], scope=pinned)
    assert result.rejections[0]["reason"] == "compilation_scope_stale"


def test_request_tenant_is_preserved_by_computer_adapter():
    from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id
    from src.app.platform.store_profile import set_active_profile_id, reset_active_profile_id
    from src.app.services.recommendation_core.workload_grounding import compile_workload_evidence_requirements
    profile_token = set_active_profile_id("electronics")
    try:
        for tenant in ("tenant-a", "tenant-b"):
            token = set_active_tenant_id(tenant)
            try:
                result = compile_workload_evidence_requirements({
                    "source": "publisher", "app_id": "same-page", "confidence": 1,
                    "retrieved_at": "2026-09-07", "minimum": {"ram_gb": 16},
                }, kind="software", name="Unseen subject")
                assert result.requirements[0].compilation_scope.tenant_id == tenant
            finally:
                reset_active_tenant_id(token)
    finally:
        reset_active_profile_id(profile_token)


def test_complete_document_does_not_replace_manifest_coverage():
    from src.app.services.research_outcome import build_research_outcome
    compiled = compile_authoritative_requirements([claim()], scope=scope())
    result = build_research_outcome(
        case_id="case", case_revision=1, operation_id="op", requirements={},
        catalog_authority="permitted", commerce_authority="none",
        research={"evidence": [{
            "requirements_completeness": "minimum_and_recommended",
            "compiled_requirements": [r.model_dump() for r in compiled.requirements],
        }]},
    )
    assert result.requirement_completeness == "partial"
    assert result.catalog_authority == "blocked"
    assert "cpu_model" in result.missing_requirement_attributes


def test_complete_scoped_obligations_do_not_require_document_section_labels():
    from src.app.services.research_outcome import build_research_outcome
    rows = [claim("ram_gb", 16), claim("storage_gb", 128)]
    for key, value in [("cpu_model", "Example CPU"), ("gpu_model", "Example GPU"),
                       ("os", "Windows 11"), ("storage_type", "nvme_ssd")]:
        rows.append({**claim(key, value), "operator": "="})
    compiled = compile_authoritative_requirements(rows, scope=scope())
    assert not compiled.rejections
    result = build_research_outcome(
        case_id="case", case_revision=1, operation_id="op", requirements={},
        catalog_authority="permitted", commerce_authority="none",
        research={"evidence": [{"compiled_requirements": [r.model_dump() for r in compiled.requirements]}]},
    )
    assert result.requirement_completeness == "complete"
    assert result.catalog_authority == "permitted"
    assert not result.missing_requirement_attributes
    # Continue through the real fit engine and terminal gate, not just a
    # completeness counter. Fixture identity is exact; no GPU equivalence is inferred.
    from src.app.services.attribute_registry import load_defs
    from src.app.services.catalog_read_model import VariantView
    from src.app.services.recommendation_core.fit import build_cards
    from src.app.services.terminal_research_reconciliation import gate_terminal_catalog_projection
    predicates = {r.attribute_key: (r.operator, r.value) for r in compiled.requirements}
    specs = {r.attribute_key: r.value for r in compiled.requirements}
    cards, summary = build_cards([
        VariantView(sku="complete-fixture", title="Fixture workstation", specs=specs,
                    price_cents=150000, currency="AUD", stock=4),
    ], predicates, defs=load_defs("electronics"))
    assert cards and cards[0].fit["overall"] == "meets"
    evaluated_shelf = _evaluated_scope_shelf(compiled)
    terminal = gate_terminal_catalog_projection(
        research_status="completed", products=[card.as_dict() for card in cards],
        product_shelves=evaluated_shelf.model_dump(mode='json'),
        catalog_authority=result.catalog_authority,
    )
    assert terminal.recommendation_status == "qualified"
    assert terminal.products[0]["sku"] == "complete-fixture"


def _evaluated_scope_shelf(compiled, *, missing=False, stale=False):
    """Explicit fictional observations pass through the real evidence/fit reducers."""
    from datetime import datetime, timedelta, timezone
    from src.app.models.orm import ProductConfiguration, ProductEvidenceObservation
    from src.app.services.accepted_catalog_projection import _decision, _identity
    from src.app.services.recommendation_core.product_shelves import ShelfCandidateInput, build_product_shelves
    from src.app.services.recommendation_core.workload_decision import configuration_hash

    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    specs = {r.attribute_key: r.value for r in compiled.requirements}
    configuration = ProductConfiguration(
        id='scoped-fixture-config', tenant_id='tenant-a', sku='complete-fixture',
        title='FICTIONAL scoped workstation', mpn='FIXTURE-ONLY-1', form_factor='laptop',
        configuration_hash=configuration_hash(sku='complete-fixture', form_factor='laptop', specs=specs),
        price_cents=150000, currency='AUD', source_url='fixture://scoped-workstation',
    )
    claims = [{**r.model_dump(), 'attribute': r.attribute_key,
        'claim_id': r.source_claim_ids[0], 'authority_status': 'verified_official',
        'artefact_name': 'FICTIONAL scoped workload', 'simulation_only': True}
        for r in compiled.requirements]
    observations = [ProductEvidenceObservation(
        id='fixture-observation-' + key, configuration_id=configuration.id,
        attribute_key=key, value_json={'value': value, 'simulation_only': True},
        claim_class='attested', evidence_status='observed', source_id='fixture:catalogue',
        source_record_id='fixture:scoped-workstation', source_excerpt='Explicit fictional test observation',
        observed_at=now-timedelta(days=31) if stale else now,
    ) for key, value in specs.items() if not (missing and key == 'os')]
    decision = _decision(configuration, claims, scope_id='shared',
        desired_outcome='FICTIONAL scoped workload', budget_cents=None,
        observations=observations, availability_status='unknown', now=now)
    return build_product_shelves([ShelfCandidateInput(
        product=_identity(configuration), title=configuration.title, price_cents=150000,
        fit_by_scope={'shared': decision},
    )])


@pytest.mark.parametrize('missing,stale', [(True, False), (False, True)])
def test_complete_requirements_cannot_qualify_missing_or_stale_product_evidence(missing, stale):
    from src.app.services.terminal_research_reconciliation import gate_terminal_catalog_projection
    rows = [claim('ram_gb', 16), claim('storage_gb', 128)]
    rows.extend({**claim(key, value), 'operator': '='} for key, value in [
        ('cpu_model', 'Example CPU'), ('gpu_model', 'Example GPU'),
        ('os', 'Windows 11'), ('storage_type', 'nvme_ssd'),
    ])
    compiled = compile_authoritative_requirements(rows, scope=scope())
    assert not compiled.rejections
    evaluated = _evaluated_scope_shelf(compiled, missing=missing, stale=stale)
    terminal = gate_terminal_catalog_projection(research_status='completed',
        products=[{'sku': 'complete-fixture'}], product_shelves=evaluated.model_dump(mode='json'),
        catalog_authority='permitted', requirement_completeness='complete')
    assert terminal.recommendation_status == 'no_qualified_products'


def test_different_workloads_cannot_complete_each_other_in_one_provider_row():
    from src.app.services.research_outcome import build_research_outcome
    rows = [claim("ram_gb", 16), claim("storage_gb", 128)]
    rows = [{**row, "artefact_name": "Workload A"} for row in rows]
    for key, value in [("cpu_model", "Example CPU"), ("gpu_model", "Example GPU"),
                       ("os", "Windows 11"), ("storage_type", "nvme_ssd")]:
        rows.append({**claim(key, value), "operator": "=", "artefact_name": "Workload B"})
    compiled = compile_authoritative_requirements(rows, scope=scope())
    assert not compiled.rejections
    result = build_research_outcome(
        case_id="case", case_revision=1, operation_id="op", requirements={},
        catalog_authority="permitted", commerce_authority="none",
        research={"evidence": [{"compiled_requirements": [r.model_dump() for r in compiled.requirements]}]},
    )
    assert result.requirement_completeness == "partial"
    assert result.catalog_authority == "blocked"
