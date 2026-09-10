"""Regression oracles for the live September 10 continuity failures."""
import pytest

@pytest.mark.parametrize('query', [
    'actually i need something with better disaster recovery like a raid 5? what else to buy?',
    'Instead I need something to keep groceries chilled.',
])
def test_unresolved_purchase_replacement_is_not_an_answer_to_old_workload(query):
    from src.app.services.subject_switch_boundary import unresolved_purchase_replacement
    decision = {'subject_role': 'PROCURE_SUBJECT', 'requested_category_label': 'Unresolved product',
                'requested_product_node': None, 'subject_from_session': False,
                'clarification_relation': 'answer'}
    assert unresolved_purchase_replacement(decision, explicit_replacement=True, additive=False)


@pytest.mark.parametrize('patch,explicit,additive', [
    ({'subject_role': 'RUN_SUBJECT_ON_PRODUCT'}, True, False),
    ({'subject_from_session': True}, True, False),
    ({'requested_product_node': 'el-6-6'}, True, False),
    ({}, False, False), ({}, True, True),
])
def test_unresolved_purchase_boundary_preserves_other_transitions(patch, explicit, additive):
    from src.app.services.subject_switch_boundary import unresolved_purchase_replacement
    decision = {'subject_role': 'PROCURE_SUBJECT', 'requested_category_label': 'Unresolved product', **patch}
    assert not unresolved_purchase_replacement(decision, explicit_replacement=explicit, additive=additive)

from src.app.services.terminal_research_narration import terminal_research_narration
from src.app.services.research_outcome import build_research_outcome
from src.app.services.case_catalog_candidates import build_case_catalog_candidate_set, buyer_category_changed
from tests.services.test_case_catalog_candidates import _database


@pytest.mark.parametrize('outcome', [
    {'held_claim_count': 16, 'parsed_claim_count': 16},
    {'failure_code': 'requirements_incomplete', 'accepted_claim_count': 2},
])
def test_workload_research_cannot_replace_a_new_purchase_answer(outcome):
    answer = 'The requested storage product is outside this catalog.'
    assert terminal_research_narration(
        research_outcome=outcome, execution_evidence={}, existing_message=answer,
        subject_role='PROCURE_SUBJECT',
    ) == answer


def test_identity_and_unreceipted_compilation_do_not_prove_ownership_or_fetch():
    result = build_research_outcome(
        case_id='case', case_revision=1, operation_id='op',
        research={'evidence': [{'canonical_title': 'Unknown example',
                               'compiled_requirements': [{'attribute': 'ram_gb', 'value': 16}]}]},
        requirements={}, catalog_authority='unknown', commerce_authority='none',
    )
    assert result.source_ownership_status != 'verified'
    assert result.fetch_status == 'not_attempted'
    assert result.accepted_claim_count == 0


@pytest.mark.parametrize('purpose,node,expected', [
    ('I need hardware for the simulation application', 'el-6-6', 'eligible'),
    ('Something comfortable to sit on instead', 'fr-7', 'out_of_category'),
])
def test_validated_purchase_node_survives_lexical_scope_reinference(purpose, node, expected):
    from sqlalchemy.orm import Session
    from src.app.services.catalog_evidence_seed import ingest_reviewed_configurations
    with Session(_database()) as db:
        ingest_reviewed_configurations(db)
        result = build_case_catalog_candidate_set(
            db, retained_purpose=purpose, tenant_id='default',
            storefront_taxonomy_handle='el-6-6', resolved_product_node=node,
        )
    assert result.taxonomy_handle == node
    assert result.status == expected
    assert result.catalog_scope.source == 'validated_semantic_proposal'


def test_validated_category_switch_does_not_require_a_literal_category_name():
    assert buyer_category_changed(
        {'selected_taxonomy_root': 'el-6-6'}, 'Something comfortable to sit on instead',
        resolved_product_node='fr-7',
    )


def test_effective_facts_keep_literal_and_retained_budget_distinct():
    from src.app.services.turn_transition import effective_turn_facts
    literal = {'buyer_query': 'Also run the simulation locally', 'canonical_budget': None}
    retained = {'budget_min': None, 'budget_max': 3000, 'mode': 'around', 'source_span': None}
    result = effective_turn_facts(literal, canonical_budget=retained)
    assert result['canonical_budget'] == retained
    assert result['literal_canonical_budget'] is None
    assert result['budget_source'] == 'accepted_case_constraints'
    assert literal['canonical_budget'] is None


def test_unresolved_purchase_cannot_fall_back_to_storefront_inventory():
    from sqlalchemy.orm import Session
    with Session(_database()) as db:
        result = build_case_catalog_candidate_set(
            db, retained_purpose='A different purchase, category not yet established',
            tenant_id='default', storefront_taxonomy_handle='el-6-6',
            unresolved_product_subject=True,
        )
    assert result.status == 'unresolved'
    assert result.configuration_ids == []
    assert result.catalog_scope.selected_taxonomy_root is None
    assert result.catalog_scope.client_context_disposition == 'rejected'
