import json
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.deps import hash_uid
from src.app.main import create_app
from src.app.models.orm import ShoppingCase, ShoppingCaseFulfillmentSelection
from src.app.services.conversation_case_state import ensure_case_state
from src.app.services.market_analysis import MarketFinding, persist_findings


@pytest.fixture
def owned_task_case(monkeypatch):
    subject = 'task-buyer-' + uuid4().hex
    case_id = 'sc-' + uuid4().hex
    key = 'case-task-test-signing-key-never-deploy'
    monkeypatch.setenv('JWT_SIGNING_KEY', key)
    monkeypatch.setenv('BUYER_IDENTITY_MODE', 'strict')
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON', json.dumps({subject: ['default']}))
    now = int(time.time())
    token = jwt.encode(dict(sub=subject, typ='access', iss='shopsquire', aud='shopsquire-api',
                            iat=now, exp=now + 300), key, algorithm='HS256')

    async def retained_case(request, params, **kwargs):
        return 200, {'products': [], 'next_questions': [], 'execution_steps': [],
            'assistant_message': 'Existing case retained.', 'decision_trace_id': str(uuid4()),
            'decision': {'lane': 'PROCUREMENT', 'subject_action': 'continue',
                         'case_operation': 'status', 'source': 'owned-case-task-fixture'}}

    monkeypatch.setattr('src.app.routers.chat._call_recommend_in_process', retained_case)
    app = create_app()
    with Session(app.state.engine) as db:
        db.add(ShoppingCase(case_id=case_id, tenant_id='default', uid=subject, status='active',
                            retained_purpose='FreeCAD workstation procurement'))
        db.commit()
        ensure_case_state(db, tenant_id='default', case_id=case_id, session_epoch=subject,
            subject_ref=hash_uid(subject), authoritative_anchor={
                'objective': 'FreeCAD workstation procurement', 'requested_quantity': 40,
                'sku': 'TASK-SKU', 'destination': 'Sydney',
                'budget': {'amount_minor': 150000, 'currency': 'AUD', 'scope': 'per_unit'}})
    return app, subject, case_id, {'Authorization': 'Bearer ' + token}


@pytest.mark.parametrize('accepted_selection', [False, True])
def test_ordinary_chat_delivers_a_shortfall_draft_without_authorizing_effects(owned_task_case, accepted_selection):
    app, subject, case_id, headers = owned_task_case
    if accepted_selection:
        with Session(app.state.engine) as db:
            db.add(ShoppingCaseFulfillmentSelection(selection_id='selection-' + case_id,
                tenant_id='default', case_id=case_id, uid=subject, revision=1,
                status='confirmed', choice='split', preferred_sku='TASK-SKU',
                requested_quantity=40, available_now=25, offers_json=[],
                selection_idempotency_key='selection-' + case_id,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)))
            # The fixture supplies a real reservation, not a buyer's stock assertion.
            db.execute(text('CREATE TABLE IF NOT EXISTS inventory_reservation '
                '(tenant_id TEXT,reservation_id TEXT,sku TEXT,location_id TEXT,quantity INTEGER,'
                'status TEXT,returned_quantity INTEGER,payload_digest TEXT,expires_at TEXT)'))
            db.execute(text('INSERT INTO inventory_reservation '
                '(tenant_id,reservation_id,sku,location_id,quantity,status,returned_quantity,payload_digest,expires_at) '
                "VALUES ('default',:id,'TASK-SKU','owned-warehouse',25,'reserved',0,'owned-fixture',:expiry)"),
                {'id': 'selection:selection-' + case_id + ':owned-warehouse',
                 'expiry': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
            db.commit()
    with TestClient(app) as client:
        response = client.post('/api/v1/chat/query', headers=headers,
            json={'uid': subject, 'shopping_case_id': case_id,
                  'query': 'Draft an email to request the unit quantity shortfall for my current request.'})
    assert response.status_code == 200, response.text
    body = response.json()
    draft = body.get('email_draft')
    assert isinstance(draft, dict), body
    assert draft['case_id'] == case_id == body['shopping_case_id']
    assert draft['case_revision'] == body['case_revision'] == 1
    assert draft['requested_quantity'] == 40
    assert draft['commerce_authority'] == 'none'
    assert draft['dispatch_authorized'] is False
    assert '40' in draft['body'] and 'Sydney' in draft['body'] and 'AUD 1500.00 per unit' in draft['body']
    if accepted_selection:
        assert draft['shortfall'] == 15, draft
        assert '15 units' in draft['body']
    else:
        assert draft['shortfall'] is None
        assert 'current_accepted_selection' in draft['missing_inputs']
    assert draft['body'] in body['assistant_message']


def test_ordinary_chat_returns_cited_market_analysis_for_the_owned_case(owned_task_case):
    app, subject, case_id, headers = owned_task_case
    now = datetime.now(timezone.utc)
    with Session(app.state.engine) as db:
        persist_findings(db, [MarketFinding('demand_shift', 'TASK-SKU', 'warn', 0.8,
            'Reviewed orders show rising demand for this SKU.', {
                'subject_type': 'sku', 'subject_id': 'TASK-SKU', 'status': 'observed',
                'source_system': 'owned-orders', 'source_record_id': case_id,
                'lineage_root': 'orders', 'provenance_chain': ['orders/' + case_id],
                'observed_at': now.isoformat(), 'effective_from': now.isoformat(),
                'effective_to': (now + timedelta(hours=1)).isoformat()}, '7d')], tenant_id='default')
        db.commit()
    with TestClient(app) as client:
        response = client.post('/api/v1/chat/query', headers=headers,
            json={'uid': subject, 'shopping_case_id': case_id,
                  'query': 'Give me market intelligence for my current request.'})
    assert response.status_code == 200, response.text
    body = response.json()
    analysis = body.get('market_intelligence')
    assert isinstance(analysis, dict), body
    assert analysis['case_id'] == case_id == body['shopping_case_id']
    assert analysis['case_revision'] == body['case_revision'] == 1
    assert analysis['delivery_status'] == 'available'
    assert analysis['market_evidence']['citations'][0]['source_record_id'] == case_id
    assert case_id in body['assistant_message']
    assert body['requested_quantity'] == 40


def test_draft_read_keeps_the_accepted_selection_and_case_revision(owned_task_case):
    app, subject, case_id, headers = owned_task_case
    with TestClient(app) as client:
        for query in ['Draft an email for the stock shortfall for my current request.',
                      'Give me market intelligence for my current request.']:
            response = client.post('/api/v1/chat/query', headers=headers,
                json={'uid': subject, 'shopping_case_id': case_id, 'query': query})
            assert response.status_code == 200, response.text
            assert response.json()['case_revision'] == 1
    with Session(app.state.engine) as db:
        assert db.execute(text('SELECT revision FROM shopping_cases WHERE case_id=:case'),
                          {'case': case_id}).scalar_one() == 1


@pytest.mark.parametrize('query,expected', [
    ('Draft an email for the unit quantity shortfall.', True),
    ('Make it 50 units and draft an email for the shortfall.', False),
    ('Draft an email for a 50 unit shortfall.', False),
    ('Write an email to reset my password.', False),
])
def test_task_read_never_consumes_a_quantity_amendment_or_unrelated_email(query, expected):
    from src.app.services.case_task_delivery import is_case_task_read
    assert is_case_task_read(query, {'requested_quantity': 40}) is expected


@pytest.mark.parametrize('valid_schema', [False, True])
def test_corrupt_derived_view_cannot_override_canonical_task_facts(owned_task_case, valid_schema):
    app, subject, case_id, headers = owned_task_case
    with Session(app.state.engine) as db:
        raw = db.execute(text('SELECT state_json FROM conversation_case_state WHERE case_id=:case'),
                         {'case': case_id}).scalar_one()
        stored = json.loads(raw)
        stored['turn_read_model'] = {'schema_version': 'obsolete-untrusted-projection',
                                    'requested_quantity': 999, 'commerce_authority': 'approved'}
        if valid_schema:
            stored['turn_read_model'] = {
                'schema_version': 'revision-bound-turn-read-model.v1', 'case_id': case_id,
                'case_revision': 1, 'transition': 'UNRESOLVED',
                'shared_constraints': {'requested_quantity': 999},
                'pending_clarification': {'action': 'none'}, 'external_research_authorized': False,
                'research_outcome': {'schema_version': 'research-outcome-v1', 'case_id': case_id,
                    'case_revision': 1, 'catalog_authority': 'permitted'},
                'requirements': {}, 'catalog_authority': 'permitted', 'commerce_authority': 'none',
                'products': [{'sku': 'NOT-CURRENT'}]}
        db.execute(text('UPDATE conversation_case_state SET state_json=:state WHERE case_id=:case'),
                   {'state': json.dumps(stored), 'case': case_id})
        db.commit()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post('/api/v1/chat/query', headers=headers,
            json={'uid': subject, 'shopping_case_id': case_id,
                  'query': 'Draft an email for the unit quantity shortfall for my current request.'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['requested_quantity'] == body['email_draft']['requested_quantity'] == 40
    assert body['case_revision'] == 1
    assert body['terminal_outcome']['commerce_authority'] == 'none'
    assert body['turn_read_model']['schema_version'] == 'revision-bound-turn-read-model.v1'
    assert body['turn_read_model']['shared_constraints']['requested_quantity'] == 40
    assert body['products'] == []
