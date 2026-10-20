"""Naming a shortfall must not recommit the buyer's total requested quantity."""
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.app.models.orm import ShoppingCaseFulfillmentSelection

from tests.api.test_chat_case_tasks import owned_task_case


@pytest.mark.parametrize('query', [
    'Draft an email to the supplier for the 25 unit shortfall.',
    'Draft an email for a 50 unit shortfall in my current request.',
])
@pytest.mark.parametrize('accepted_selection', [False, True])
def test_shortfall_count_keeps_canonical_total_and_material_revision(owned_task_case, query, accepted_selection):
    app, subject, case_id, headers = owned_task_case
    if accepted_selection:
        with Session(app.state.engine) as db:
            selection_id = 'shortfall-' + case_id
            now = datetime.now(timezone.utc)
            db.add(ShoppingCaseFulfillmentSelection(selection_id=selection_id,
                tenant_id='default', case_id=case_id, uid=subject, revision=1,
                status='confirmed', choice='split', preferred_sku='TASK-SKU',
                requested_quantity=40, available_now=15, offers_json=[],
                selection_idempotency_key=selection_id, created_at=now, updated_at=now))
            db.execute(text('INSERT INTO inventory_reservation '
                '(tenant_id,reservation_id,sku,location_id,quantity,status,returned_quantity,payload_digest,expires_at) '
                "VALUES ('default',:id,'TASK-SKU','task-warehouse',15,'reserved',0,'shortfall-fixture',:expiry)"),
                {'id': 'selection:' + selection_id + ':task-warehouse',
                 'expiry': (now + timedelta(hours=1)).isoformat()})
            db.commit()
    with TestClient(app) as client:
        response = client.post('/api/v1/chat/query', headers=headers,
            json={'uid': subject, 'shopping_case_id': case_id, 'query': query})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['read_only_case_task'] is True
    assert body['case_revision'] == 1
    assert body['retained_buyer_facts']['requested_quantity'] == 40
    assert body['email_draft']['requested_quantity'] == 40
    if accepted_selection:
        assert body['email_draft']['shortfall'] == 25
        assert '25 units' in body['email_draft']['body']
        assert '50 units' not in body['email_draft']['body']
    else:
        assert body['email_draft']['shortfall'] is None
        assert 'current_accepted_selection' in body['email_draft']['missing_inputs']
    assert body['email_draft']['dispatch_authorized'] is False
    with Session(app.state.engine) as db:
        assert db.scalar(text('SELECT revision FROM shopping_cases WHERE case_id=:case'), {'case': case_id}) == 1
