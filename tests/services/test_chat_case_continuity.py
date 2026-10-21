import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from src.app.services import chat_case_continuity as continuity

@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:')
    with Session(engine) as db:
        for ddl in [
            'CREATE TABLE shopping_cases(case_id TEXT,tenant_id TEXT,uid TEXT)',
            'CREATE TABLE conversation_case_state(id TEXT,tenant_id TEXT,case_id TEXT,session_epoch TEXT,subject_ref TEXT)',
            'CREATE TABLE conversation_case_amendment(case_state_id TEXT,tenant_id TEXT,case_id TEXT,session_epoch TEXT,dialogue_act TEXT,status TEXT,created_at TEXT)']:
            db.execute(text(ddl))
        db.execute(text("INSERT INTO shopping_cases VALUES ('case','tenant','buyer')"))
        db.execute(text("INSERT INTO conversation_case_state VALUES ('s','tenant','case','epoch','subject')"))
        db.execute(text("INSERT INTO conversation_case_amendment VALUES ('s','tenant','case','epoch','turn_transition','accepted','2026-10-01T00:00:00+00:00')"))
        yield db
    engine.dispose()

def restore(db,**changes):
    return continuity.restore_case_id(db,**{**dict(tenant_id='tenant',uid='buyer',session_epoch='epoch',subject_ref='subject'),**changes})

def test_restores_only_committed_owned_session_case(db):
    assert restore(db)=='case'
    for change in [{'tenant_id':'other'},{'uid':'other'},{'session_epoch':'new'},{'subject_ref':'other'}]:
        assert restore(db,**change) is None
    db.execute(text("UPDATE conversation_case_amendment SET status='pending'"))
    assert restore(db) is None

def test_tied_latest_cases_require_explicit_selection(db):
    db.execute(text("INSERT INTO shopping_cases VALUES ('case2','tenant','buyer')"))
    db.execute(text("INSERT INTO conversation_case_state VALUES ('s2','tenant','case2','epoch','subject')"))
    db.execute(text("INSERT INTO conversation_case_amendment VALUES ('s2','tenant','case2','epoch','turn_transition','accepted','2026-10-01T00:00:00+00:00')"))
    with pytest.raises(ValueError,match='ambiguous'):restore(db)
    db.execute(text("UPDATE conversation_case_amendment SET created_at='2026-10-01T00:00:01+00:00' WHERE case_id='case2'"))
    assert restore(db)=='case2'

def test_current_quantity_projection_requires_matching_revision():
    out={'case_id':'case','case_revision':3,'procurement_case_state':{'case_id':'case','revision':3,'requested_quantity':8}}
    continuity.project_retained_facts(out)
    assert out['requested_quantity']==8
    assert out['confirmed_slots']['order_quantity']==8
    assert out['retained_buyer_facts']['requested_quantity']==8
    for bad in [{'case_id':'other'},{'revision':2},{'requested_quantity':True}]:
        row={'case_id':'case','case_revision':3,'procurement_case_state':{**out['procurement_case_state'],**bad}}
        continuity.project_retained_facts(row)
        assert 'requested_quantity' not in row


def test_recall_projects_budget_destinations_and_unresolved_deadline_without_authority():
    row={'case_id':'case','case_revision':4,'procurement_case_state':{
        'case_id':'case','revision':4,'requested_quantity':8,
        'budget':{'amount_minor':960000,'currency':'AUD','scope':'total'},
        'destinations':[{'location_ref':'Parramatta','quantity':8,'location_kind':'city'}],
        'temporal':{'original_expression':'next Friday','resolution_status':'unresolved'},
        'authority':{'purchase':'approved'}}}
    continuity.project_retained_facts(row)
    facts=row['retained_buyer_facts']
    assert facts['budget']['scope']=='total'
    assert facts['destinations'][0]['location_ref']=='Parramatta'
    assert 'authority' not in facts
    summary=continuity.retained_facts_message(facts)
    assert 'AUD 9600.00 total' in summary and 'Parramatta' in summary
    assert 'next Friday (unresolved)' in summary
    assert 'approved' not in summary
    for change in ({'case_id':'other'},{'revision':3}):
        invalid={**row,'procurement_case_state':{**row['procurement_case_state'],**change}}
        continuity.project_retained_facts(invalid)
        assert 'retained_buyer_facts' not in invalid


def test_recall_does_not_promote_malformed_money_or_destinations():
    row={'case_id':'case','case_revision':1,'procurement_case_state':{
        'case_id':'case','revision':1,'budget':{'amount_minor':True,'currency':'AUD','scope':'total'},
        'destinations':[{'location_ref':'Sydney','quantity':-2}]}}
    continuity.project_retained_facts(row)
    assert not row.get('retained_buyer_facts')


def test_literal_quantity_survives_failed_model_without_inventing_specs():
    from src.app.services.chat_turn_projection import _extract_confirmed_slots
    assert _extract_confirmed_slots(query='work laptops budget 1200 to 1500, need 10')['order_quantity'] == 10
    assert 'order_quantity' not in _extract_confirmed_slots(query='Need 16 GB memory')


def test_explicit_deadline_is_retained_without_model_and_not_invented_on_recall():
    from src.app.services.chat_turn_projection import _extract_confirmed_slots
    assert _extract_confirmed_slots(query='Actually deliver by 2030-10-12T17:00:00+11:00.')['deadline'] == '2030-10-12T17:00:00+11:00'
    assert 'deadline' not in _extract_confirmed_slots(query='Summarise my requested deadline.')
    assert 'deadline' not in _extract_confirmed_slots(query='A laptop made by Dell.')


def test_explicit_budget_currency_replaces_retained_currency_without_defaulting():
    from src.app.services.chat_turn_projection import _extract_confirmed_slots
    assert _extract_confirmed_slots(query='Change my budget to USD 10000 total for all 8.')['currency']=='USD'
    assert 'currency' not in _extract_confirmed_slots(query='Change my budget to 10000 total for all 8.')
    assert 'currency' not in _extract_confirmed_slots(query='Need CAD modelling with a budget of 1500.')
    assert _extract_confirmed_slots(query='Need CAD modelling with AUD 1500 per unit.')['currency']=='AUD'


def test_delivery_amendment_reuses_existing_grammar_and_interrupts_workload_question():
    from src.app.services.chat_turn_projection import _extract_confirmed_slots
    from src.app.services.clarification_state import commercial_obligations
    for place in ('Parramatta','Osaka','warehouse B'):
        query=f'Actually deliver to {place}.'
        assert _extract_confirmed_slots(query=query)['destination']==place
        assert 'destination' in commercial_obligations(query)


def test_material_budget_scope_question_survives_blocked_catalog():
    row = {'requested_quantity': 10, 'confirmed_slots': {'budget_max': 1500},
           'next_questions': [], 'products': [], 'commerce_authority': 'none'}
    continuity.project_budget_question(row)
    assert row['next_questions'][0]['id'] == 'budget_scope'
    assert row['commerce_authority'] == 'none'
    row['confirmed_slots']['budget_scope'] = 'per_unit'
    row['next_questions'] = []
    continuity.project_budget_question(row)
    assert row['next_questions'] == []


def test_terminal_and_api_present_the_same_material_question():
    from src.app.services.chat_terminal_projection import project_chat_terminal
    out = {'research_outcome': {}, 'next_questions': [{'id': 'budget_scope', 'text': 'Per item or total?'}]}
    project_chat_terminal(out=out, server_research_result={}, server_research_failure=None,
        params_case_patch_idempotency_key='turn',
        ambiguity_exploration={'next_question': {'id':'research_scope','text':'Which workload?'}},
        active_shopping_case_id='case', decision_trace_id='trace', data={}, products=[],
        effective_turn_facts=lambda facts, **kwargs: facts)
    assert out['terminal_outcome']['next_questions'] == out['next_questions']
    assert out['terminal_outcome']['next_questions'][0]['id'] == 'budget_scope'
