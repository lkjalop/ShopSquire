import json
import time
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.main import create_app
from src.app.models.orm import RequirementProposal, ShoppingCase


@pytest.mark.parametrize('mode', ['continuation', 'fresh', 'replacement'])
def test_evidence_proposal_uses_the_final_owned_case(monkeypatch, mode):
    subject = 'evidence-buyer-' + uuid4().hex
    case_id = 'sc-' + uuid4().hex
    signing_key = 'owned-evidence-intake-test-signing-key-never-deploy'
    monkeypatch.setenv('JWT_SIGNING_KEY', signing_key)
    monkeypatch.setenv('BUYER_IDENTITY_MODE', 'strict')
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON', json.dumps({subject: ['default']}))
    now = int(time.time())
    token = jwt.encode(dict(sub=subject, typ='access', role='buyer', iss='shopsquire',
                            aud='shopsquire-api', iat=now, exp=now + 300), signing_key,
                       algorithm='HS256')

    async def unavailable_interpreter(request, params, **kwargs):
        return 200, {
            'products': [], 'next_questions': [], 'execution_steps': [],
            'assistant_message': 'Interpreter unavailable; requirements remain unverified.',
            'decision_trace_id': str(uuid4()),
            'decision': {'subject_action': 'switch', 'clarification_relation': 'none',
                         'source': 'fallback:model_unavailable', 'lane': 'SEARCH',
                         'request_scope': 'product'},
        }

    monkeypatch.setattr('src.app.routers.chat._call_recommend_in_process', unavailable_interpreter)
    app = create_app()
    with Session(app.state.engine) as db:
        db.add(ShoppingCase(case_id=case_id, tenant_id='default', uid=subject,
                            status='active', retained_purpose='Factory simulation workstation'))
        db.commit()
    with TestClient(app) as client:
        response = client.post('/api/v1/chat/query', headers={'Authorization': 'Bearer ' + token},
            json={'uid': subject, 'shopping_case_id': case_id if mode != 'fresh' else None,
                  'query': ("Forget that request. Instead I need gaming laptops for Baldur's Gate 3."
                            if mode == 'replacement' else
                            'Please read these specifications for my current request.'),
                  'image_ocr_text': 'Minimum RAM: 32 GB\nMinimum storage: 1000 GB SSD',
                  'image_hash': 'controlled-requirements-document-' + uuid4().hex,
                  'image_intent': 'requirements_document', 'image_labels': ['requirements document']})
    assert response.status_code == 200, response.text
    body = response.json()
    proposal = body['buyer_requirement_proposal']
    final_case = body['shopping_case_id']
    assert proposal['case_id'] == final_case
    assert final_case.startswith('sc-')
    if mode == 'continuation':
        assert final_case == case_id
        assert body['decision']['subject_action'] == 'continue'
    else:
        assert final_case != case_id
        if mode == 'replacement':
            assert body['decision']['subject_action'] == 'switch'
    assert body['products'] == []
    assert body['terminal_outcome']['commerce_authority'] == 'none'
    with Session(app.state.engine) as db:
        stored = db.execute(select(RequirementProposal).where(
            RequirementProposal.proposal_id == proposal['proposal_id'],
        )).scalar_one()
        assert stored.case_id == final_case and stored.uid == subject
        assert db.execute(select(ShoppingCase).where(
            ShoppingCase.case_id == final_case,
        )).scalar_one().status == 'active'
