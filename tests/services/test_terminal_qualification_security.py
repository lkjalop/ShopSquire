import pytest
from src.app.services.terminal_qualification import qualified_configuration_ids, terminal_questions
from src.app.services.terminal_research_narration import terminal_research_narration
from src.app.services.terminal_research_reconciliation import gate_terminal_catalog_projection


@pytest.mark.parametrize('authority', ['unknown', 'blocked', 'permitted'])
@pytest.mark.parametrize('role', ['RUN_SUBJECT_ON_PRODUCT', 'PROCURE_SUBJECT'])
def test_partial_evidence_cannot_preserve_positive_qualification(authority, role):
    outcome = {'identity': {'title': 'Unfamiliar workload'}, 'accepted_claim_count': 5,
        'requirement_completeness': 'partial', 'catalog_authority': authority,
        'missing_requirement_attributes': ['os'], 'failure_code': 'publisher_not_yet_accepted'}
    message = terminal_research_narration(research_outcome=outcome, execution_evidence={},
        existing_message='The requirements qualified 2 catalog configurations.', subject_role=role)
    assert 'qualified 2' not in message
    assert 'Missing evidence: os' in message
    assert qualified_configuration_ids(outcome, {'shelves': []}) == []
    questions = terminal_questions([{'reason': 'named_workload_evidence_unresolved',
        'workload_subjects': ['Unfamiliar workload'], 'text': 'No provider returned requirements'}], outcome)
    assert questions[0]['obligation_ids'] == ['requirement:os']
    assert 'No provider' not in questions[0]['text']


def test_one_workload_cannot_retire_another_workloads_obligation():
    outcome = {'identity': {'title': 'Kingdom Come: Deliverance II'},
               'accepted_claim_count': 5, 'requirement_completeness': 'complete'}
    unrelated = {'reason': 'named_workload_evidence_unresolved', 'workload_subjects': ['Other game']}
    combined = {**unrelated, 'workload_subjects': ['Other game', 'Kingdom Come Deliverance 2']}
    bound = {**unrelated, 'workload_subjects': ['Kingdom Come Deliverance 2']}
    assert terminal_questions([unrelated, combined, bound], outcome) == [unrelated, combined]


def test_nonempty_conditional_shelf_is_not_qualified():
    result = gate_terminal_catalog_projection(research_status='completed', products=[{'sku': 'legacy'}],
        product_shelves={'shelves': [{'initial': [{'fit_status': 'conditional'}]}]},
        catalog_authority='permitted', requirement_completeness='complete')
    assert result.recommendation_status == 'no_qualified_products'


def test_held_claims_do_not_preserve_positive_text_when_authority_unknown():
    message = terminal_research_narration(
        research_outcome={'identity': {'title': 'A workload'}, 'catalog_authority': 'unknown',
                          'accepted_claim_count': 2, 'held_claim_count': 3},
        execution_evidence={}, existing_message='Research qualified 2 configurations.')
    assert 'qualified 2' not in message
    assert 'not established authority' in message


def test_unverified_fit_cannot_offer_a_real_fit_budget_upgrade():
    from src.app.services.terminal_qualification import terminal_questions
    questions = [{"goal":"resolve_budget_capability_gap", "text":"Budget floor is 1919",
                  "options":[{"id":"stretch", "label":"Stretch for the real fit"}]},
                 {"goal":"resolve_named_workload", "text":"Which version?"}]
    result = terminal_questions(questions, {"catalog_authority":"unknown"})
    assert result == [questions[1]]
