"""Case ownership under admitted research consent and a failed interpreter.

The interpreter/admission are controlled boundaries; this does not qualify a
live provider. Native registered-buyer browser journeys cover the real consent UI.
"""
import json
import time
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.main import create_app
from src.app.models.orm import ShoppingCase
from src.app.services.chat_research_entry import ResearchEntry


@pytest.mark.parametrize('mode', ['continuation', 'replacement', 'fresh', 'foreign'])
def test_admitted_research_preserves_the_owned_case_without_weakening_replacement(monkeypatch, mode):
    subject = 'research-buyer-' + uuid4().hex
    case_id = 'sc-' + uuid4().hex
    signing_key = 'controlled-research-continuity-test-key-never-deploy'
    monkeypatch.setenv('JWT_SIGNING_KEY', signing_key)
    monkeypatch.setenv('BUYER_IDENTITY_MODE', 'strict')
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON', json.dumps({subject: ['default']}))
    monkeypatch.setenv('EXTERNAL_RESEARCH_SEARCH_URL', 'http://127.0.0.1:1/search?q={query}')
    now = int(time.time())
    token = jwt.encode(dict(sub=subject, typ='access', role='buyer', iss='shopsquire',
                            aud='shopsquire-api', iat=now, exp=now + 300), signing_key, algorithm='HS256')
    monkeypatch.setattr('src.app.services.chat_research_entry.research_entry_authorization',
        lambda **kwargs: ResearchEntry({'external_research_enabled': True}, True, False, True, 'buyer_action'))

    async def unavailable_interpreter(request, params, **kwargs):
        return 200, dict(products=[], next_questions=[], execution_steps=[],
            assistant_message='Interpreter unavailable; no fit authority.', decision_trace_id=str(uuid4()),
            decision=dict(subject_action='switch', clarification_relation='none',
                source='fallback:model_unavailable', lane='SEARCH', request_scope='product'))

    monkeypatch.setattr('src.app.routers.chat._call_recommend_in_process', unavailable_interpreter)
    app = create_app()
    with Session(app.state.engine) as db:
        db.add(ShoppingCase(case_id=case_id, tenant_id='default',
            uid='foreign-buyer' if mode == 'foreign' else subject, status='active',
            retained_purpose='I need 30 laptops for FreeCAD 1.0 mechanical design.'))
        db.commit()
    query = ('Instead I need gaming laptops for Blender rendering.' if mode == 'replacement'
             else 'Search online for the official FreeCAD 1.0 requirements.')
    with TestClient(app) as client:
        response = client.post('/api/v1/chat/query', headers={'Authorization': 'Bearer ' + token},
            json={'uid': subject, 'shopping_case_id': None if mode == 'fresh' else case_id,
                  'session_id': 'epoch-' + uuid4().hex, 'query': query, 'external_research_consent': True})
    if mode == 'foreign':
        assert response.status_code == 403
        return
    assert response.status_code == 200, response.text
    body = response.json()
    if mode == 'continuation':
        assert body['case_id'] == case_id
        assert body['decision']['subject_action'] == 'continue'
    else:
        assert body['case_id'] != case_id
    assert body['products'] == []
    assert body['terminal_outcome']['commerce_authority'] == 'none'
    with Session(app.state.engine) as db:
        original = db.execute(select(ShoppingCase).where(ShoppingCase.case_id == case_id)).scalar_one()
        assert original.status == ('superseded' if mode == 'replacement' else 'active')
