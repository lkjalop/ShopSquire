"""Read-only recall must leave an accepted stock selection on its current revision."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.models.orm import ShoppingCaseFulfillmentSelection
from tests.api.test_chat_case_tasks import owned_task_case


@pytest.mark.parametrize('query', [
    'Summarise my quantity, per-unit budget and delivery destination without taking any action.',
    'How many laptops did I ask for and what was my budget and delivery destination?',
])
def test_case_recall_preserves_material_revision_and_accepted_selection(owned_task_case, query):
    app, subject, case_id, headers = owned_task_case
    now = datetime.now(timezone.utc)
    with Session(app.state.engine) as db:
        db.add(ShoppingCaseFulfillmentSelection(selection_id='read-' + case_id,
            tenant_id='default', case_id=case_id, uid=subject, revision=1,
            status='confirmed', choice='split', preferred_sku='TASK-SKU',
            requested_quantity=40, available_now=15, offers_json=[],
            selection_idempotency_key='read-' + case_id, created_at=now, updated_at=now))
        db.commit()
    with TestClient(app) as client:
        response = client.post('/api/v1/chat/query', headers=headers,
            json={'uid': subject, 'shopping_case_id': case_id, 'query': query})
    assert response.status_code == 200, response.text
    with Session(app.state.engine) as db:
        revision = db.scalar(text('SELECT revision FROM shopping_cases WHERE case_id=:case'), {'case': case_id})
        assert revision == 1, 'A read invalidated the revision bound to the accepted selection'
        assert db.scalar(text('SELECT COUNT(*) FROM shopping_case_fulfillment_selections '
            "WHERE case_id=:case AND revision=:revision AND status='confirmed'"),
            {'case': case_id, 'revision': revision}) == 1
    body = response.json()
    assert body['case_revision'] == 1
    assert body['read_only_case_task'] is True
    assert body['retained_buyer_facts']['requested_quantity'] == 40
    assert '40 units' in body['assistant_message']
    assert 'AUD 1500.00 per unit' in body['assistant_message']
    assert 'Sydney' in body['assistant_message']
    assert body['terminal_outcome']['commerce_authority'] == 'none'
