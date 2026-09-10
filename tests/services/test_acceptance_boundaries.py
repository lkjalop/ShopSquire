import pytest
from src.app.services.recommendation_core.requirement_scope import resolve_requirement_scope


def test_total_budget_is_not_a_per_unit_allowance():
    from src.app.services.catalog_shortfall_projection import acceptance_budget
    assert acceptance_budget({'procurement_case_state': {
        'budget': {'amount_minor': 300001, 'scope': 'total', 'currency': 'AUD'},
        'requested_quantity': 10,
    }}) == (30000, 10)


def test_ambiguous_bulk_budget_is_not_silently_unbounded():
    from src.app.services.catalog_shortfall_projection import acceptance_budget
    with pytest.raises(ValueError, match='budget_scope_unresolved'):
        acceptance_budget({'procurement_case_state': {
            'budget': {'amount_minor': 300000, 'scope': 'unknown'}, 'requested_quantity': 10,
        }})


@pytest.mark.parametrize('quantity', [0, -1, True, '10'])
def test_invalid_quantity_cannot_expand_acceptance_allowance(quantity):
    from src.app.services.catalog_shortfall_projection import acceptance_budget
    with pytest.raises(ValueError, match='quantity_unresolved'):
        acceptance_budget({'procurement_case_state': {'requested_quantity': quantity}})


def test_zero_and_per_unit_budgets_are_preserved():
    from src.app.services.catalog_shortfall_projection import acceptance_budget
    for amount in (0, 300000):
        assert acceptance_budget({'procurement_case_state': {
            'requested_quantity': 10,
            'budget': {'amount_minor': amount, 'scope': 'per_unit', 'currency': 'AUD'},
        }}) == (amount, 10)


def test_ram_only_cannot_complete_hardware_manifest():
    from src.app.services.recommendation_core.requirement_scope import accepted_requirement_gaps
    scope = resolve_requirement_scope(tenant_id='default', profile_id='electronics',
        product_type='el-6-6', relationship='RUN_SUBJECT_ON_PRODUCT')
    gaps = accepted_requirement_gaps([{'attribute':'ram_gb', 'authority_status':'verified_official',
        'artefact_name':'Example', 'compilation_scope':scope.model_dump(mode='json')}], tenant_id='default')
    assert 'cpu_model' in gaps and 'gpu_model' in gaps and 'os' in gaps


def test_complete_scope_is_per_identity_not_union_of_subjects():
    from src.app.services.recommendation_core.requirement_scope import accepted_requirement_gaps
    scope = resolve_requirement_scope(tenant_id='default', profile_id='electronics',
        product_type='el-6-6', relationship='RUN_SUBJECT_ON_PRODUCT')
    claims = [{'attribute':key, 'authority_status':'verified_official', 'artefact_name':'Example',
        'compilation_scope':scope.model_dump(mode='json')} for key in scope.required_attributes]
    assert accepted_requirement_gaps(claims, tenant_id='default') == []
    claims[-1]['artefact_name'] = 'Different product'
    assert accepted_requirement_gaps(claims, tenant_id='default')
    assert accepted_requirement_gaps(claims, tenant_id='other-tenant')


def test_stale_or_forged_manifest_cannot_establish_completeness():
    from src.app.services.recommendation_core.requirement_scope import accepted_requirement_gaps
    scope = resolve_requirement_scope(tenant_id='default', profile_id='electronics',
        product_type='el-6-6', relationship='RUN_SUBJECT_ON_PRODUCT').model_dump(mode='json')
    scope['required_attributes'] = ['ram_gb']
    assert 'manifest_scope_stale_or_mismatched' in accepted_requirement_gaps([
        {'attribute': 'ram_gb', 'authority_status': 'verified_official',
         'artefact_name': 'Example', 'compilation_scope': scope}], tenant_id='default')


def test_acceptance_budget_rejects_stale_case_revision():
    from unittest.mock import Mock
    from src.app.services.catalog_shortfall_projection import read_acceptance_budget
    db = Mock()
    db.execute.return_value.all.return_value = [(2, {})]
    with pytest.raises(ValueError, match='budget_case_revision_conflict'):
        read_acceptance_budget(db, tenant_id='default', case_id='case', expected_revision=1)
