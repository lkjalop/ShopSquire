import json

import pytest
from fastapi.testclient import TestClient

from src.app.main import create_app


@pytest.mark.parametrize('path', ['/api/v1/chat/query', '/api/v1/chat/stream'])
def test_guard_block_has_a_complete_non_authoritative_terminal_outcome(monkeypatch, path):
    async def blocked(*args, **kwargs):
        return {'blocked':True, 'assistant_message':'Request blocked by recommendation guard',
                'products':[], 'trace_id':'guard-trace', 'action_executed':False}
    monkeypatch.setattr('src.app.routers.chat._chat_query_impl', blocked)
    with TestClient(create_app()) as client:
        response = client.post(path, json={'uid':'guard-buyer', 'query':'fixture block'},
                               headers={'x-api-key':'local-merchant-key'})
    assert response.status_code == 200, response.text
    if path.endswith('/stream'):
        frame = next(frame for frame in response.text.split('\n\n') if frame.startswith('event: answer'))
        body = json.loads(frame.split('data: ', 1)[1])
    else:
        body = response.json()
    terminal = body['terminal_outcome']
    assert terminal['recommendation_status'] == 'blocked'
    assert terminal['catalog_authority'] == 'blocked'
    assert terminal['commerce_authority'] == 'none'
    assert terminal['case_id'] is None and terminal['case_revision'] is None
    assert terminal['assistant_message'] == body['assistant_message']
    assert terminal['products'] == []
