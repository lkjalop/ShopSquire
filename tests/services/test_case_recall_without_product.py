import pytest

from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_router import _active_case_read_decision


@pytest.mark.parametrize('query', [
    'Remind me how many laptops I requested.',
    'Summarise my quantity and budget.',
    'What is happening with my request?',
    'How many laptops did I ask for and what was my budget and delivery destination?',
    'What market intelligence do you have on lead times and laptop supply? Keep my current request.',
])
def test_an_unresolved_owned_case_can_be_read_without_inventing_a_product(query):
    envelope = TurnEnvelope(tenant_id='shop',uid='buyer',trace_id='read',query=query,
        session={'active_workflow_lane':'PROCUREMENT',
            'procurement_case_state':{'case_id':'owned-case','revision':6},
            'accepted_constraints':{'quantity':8,'budget_scope':'per_unit'}})
    result = _active_case_read_decision(envelope)
    assert result is not None
    assert result.subject_action == 'continue'
    assert result.quantity == 8
    assert result.node_handle is None
    assert result.exact_product_sku is None
    assert result.case_operation in {'status','summary'}


@pytest.mark.parametrize('query', ['New search: remind me about laptops.', 'Remind me how many I requested.'])
def test_recall_text_cannot_create_a_case_or_product_on_cold_start(query):
    envelope = TurnEnvelope(tenant_id='shop',uid='buyer',trace_id='cold',query=query)
    assert _active_case_read_decision(envelope) is None
