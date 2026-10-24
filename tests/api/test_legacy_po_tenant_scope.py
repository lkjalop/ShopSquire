"""Legacy PO commands must use the authenticated operator's tenant at the sink."""
import uuid
import pytest
from fastapi.testclient import TestClient
from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services.fulfillment import repository
from src.app.services.operator_tenant_membership import grant_membership,principal_hash_for_api_key


@pytest.mark.parametrize('action,state,body',[
    ('propose-po','SELECTED',{}),
    ('execute-po','PROCUREMENT_APPROVAL_REQUIRED',{}),
    ('record-receipt','READY_TO_SHIP',{'quantity':1}),
    ('record-invoice','READY_TO_SHIP',{'quantity':1,'amount_cents':100}),
    ('complete','READY_TO_SHIP',{}),
])
def test_po_commands_cannot_cross_into_default_tenant(monkeypatch,action,state,body):
    key='isolated-po-tenant-key'
    tenant='po-tenant-'+uuid.uuid4().hex
    monkeypatch.setenv('OWNER_API_KEY',key)
    monkeypatch.setenv('OPERATOR_TENANT_MEMBERSHIP_MODE','strict')
    monkeypatch.setenv('FULFILLMENT_PO_TRANSPORT','sandbox')
    monkeypatch.setenv('FULFILLMENT_THREE_WAY_MATCH_ENABLED','0')
    def seed(db,scope):
        return repository.create_case(db,initial_state=state,buyer_uid_hash='buyer',source_trace_id=None,
            requested_by='buyer',tenant_id=scope,state_json={
                'purchase_order':{'status':'proposed','quantity':1,'unit_amount_cents':100,'total_amount_cents':100},
                'draft':{'commercial_scope':{'quantity':1}},
                'validated_quote':{'quoted_quantity':1,'unit_amount_cents':100}})
    with db_session() as db:
        grant_membership(db,principal_hash=principal_hash_for_api_key(key),tenant_id=tenant,role='owner',
            auth_method='api_key',created_by='isolated-fixture')
        foreign=seed(db,'default');own=seed(db,tenant);db.commit()
    with TestClient(create_app(),headers={'x-api-key':key,'x-tenant-id':tenant}) as client:
        denied=client.post(f'/api/v1/fulfillment/cases/{foreign}/{action}',json=body)
        assert denied.status_code==404,denied.text
        allowed=client.post(f'/api/v1/fulfillment/cases/{own}/{action}',json=body)
        assert allowed.status_code==200,allowed.text
    with db_session() as db:
        assert repository.current_version(db,foreign,'default').event=='case_opened'


def test_legacy_operator_reads_and_history_are_scoped(monkeypatch):
    key='isolated-po-read-key';tenant='po-read-'+uuid.uuid4().hex
    monkeypatch.setenv('OWNER_API_KEY',key)
    monkeypatch.setenv('OPERATOR_TENANT_MEMBERSHIP_MODE','strict')
    trace='trace-'+uuid.uuid4().hex
    with db_session() as db:
        grant_membership(db,principal_hash=principal_hash_for_api_key(key),tenant_id=tenant,role='owner',
            auth_method='api_key',created_by='isolated-fixture')
        foreign=repository.create_case(db,initial_state='NEW',buyer_uid_hash='buyer',source_trace_id=trace,
            requested_by='buyer',tenant_id='default',state_json={'draft':{'body':'PRIVATE_SUPPLIER_CANARY'}})
        own=repository.create_case(db,initial_state='NEW',buyer_uid_hash='buyer',source_trace_id=None,
            requested_by='buyer',tenant_id=tenant,state_json={});db.commit()
    app=create_app()
    with TestClient(app,headers={'x-api-key':key,'x-tenant-id':tenant}) as client:
        listed=client.get('/api/v1/fulfillment/cases')
        assert listed.status_code==200
        identifiers={row['case_id'] for row in listed.json()['cases']}
        assert own in identifiers and foreign not in identifiers
        for suffix in ['operator-view','okf','as-of?t=2099-01-01',
                       'economics','margin-advice','supplier-candidates','rfq-fanout','change-economics']:
            denied=client.get(f'/api/v1/fulfillment/cases/{foreign}/{suffix}')
            assert denied.status_code==404,denied.text
            assert 'PRIVATE_SUPPLIER_CANARY' not in denied.text
            assert client.get(f'/api/v1/fulfillment/cases/{own}/{suffix}').status_code==200
        assert client.get(f'/api/v1/fulfillment/cases/by-trace/{trace}/operator-view').status_code==404
    with TestClient(app) as anonymous:
        assert anonymous.get(f'/api/v1/fulfillment/cases/{foreign}/as-of?t=2099-01-01').status_code==401


@pytest.mark.parametrize('action,body', [
    ('assess', {'requested_qty': 3, 'in_stock': 1, 'item_ref': 'opaque-product'}),
    ('compare-quotes', {'quotes': []}),
    ('supersede', {}),
    ('draft-quote', {'item_ref': 'opaque-product', 'quantity': 3}),
    ('edit-draft', {'body': 'Please confirm availability.'}),
    ('request-approval', {}),
    ('start-qualification', {}),
    ('qualify', {'qualified': True}),
    ('request-info', {'question': 'Please confirm availability.'}),
    ('supplier-info', {'answer': 'Three units available.'}),
    ('validate-quote', {}),
    ('options', {}),
    ('propose-change', {'kind': 'cancel'}),
    ('cancel', {}),
    ('notify-buyer', {'to_email': 'buyer@example.invalid'}),
    ('record-ack', {'ack_ref': 'example'}),
])
def test_operator_workflow_commands_reject_foreign_case(monkeypatch, action, body):
    key = 'workflow-scope-key'
    tenant = 'workflow-' + uuid.uuid4().hex
    monkeypatch.setenv('OWNER_API_KEY', key)
    monkeypatch.setenv('OPERATOR_TENANT_MEMBERSHIP_MODE', 'strict')
    monkeypatch.setenv('FULFILLMENT_CHANGE_ORDER_ENABLED', '1')
    monkeypatch.setenv('FULFILLMENT_PO_TRANSPORT', 'sandbox')
    monkeypatch.setenv('FULFILLMENT_OUTBOUND_TRANSPORT', 'sandbox')
    with db_session() as db:
        grant_membership(db, principal_hash=principal_hash_for_api_key(key), tenant_id=tenant,
                         role='owner', auth_method='api_key', created_by='fixture')
        case_id = repository.create_case(db, initial_state='READY_TO_SHIP', buyer_uid_hash='buyer',
            source_trace_id=None, requested_by='buyer', tenant_id='default', state_json={
                'purchase_order': {'total_amount_cents': 123400},
                'draft': {'body': 'PRIVATE_SUPPLIER_CANARY'}})
        db.commit()
    with TestClient(create_app(), headers={'x-api-key': key, 'x-tenant-id': tenant}) as client:
        response = client.post(f'/api/v1/fulfillment/cases/{case_id}/{action}', json=body)
        assert response.status_code == 404, response.text
        assert 'PRIVATE_SUPPLIER_CANARY' not in response.text
    with db_session() as db:
        assert repository.current_version(db, case_id, 'default').event == 'case_opened'


def test_owned_cancellation_uses_its_tenant_economics(monkeypatch):
    key = 'cancellation-scope-key'
    tenant = 'cancel-' + uuid.uuid4().hex
    monkeypatch.setenv('OWNER_API_KEY', key)
    monkeypatch.setenv('OPERATOR_TENANT_MEMBERSHIP_MODE', 'strict')
    monkeypatch.setenv('FULFILLMENT_CHANGE_ORDER_ENABLED', '1')
    monkeypatch.setenv('FULFILLMENT_REFUND_ENABLED', '0')
    with db_session() as db:
        grant_membership(db, principal_hash=principal_hash_for_api_key(key), tenant_id=tenant,
                         role='owner', auth_method='api_key', created_by='fixture')
        case_id = repository.create_case(db, initial_state='READY_TO_SHIP', buyer_uid_hash='buyer',
            source_trace_id=None, requested_by='buyer', tenant_id=tenant,
            state_json={'purchase_order': {'total_amount_cents': 123400}})
        db.commit()
    with TestClient(create_app(), headers={'x-api-key': key, 'x-tenant-id': tenant}) as client:
        economics = client.get(f'/api/v1/fulfillment/cases/{case_id}/change-economics')
        assert economics.status_code == 200, economics.text
        assert economics.json()['committed_cost_cents'] == 123400
        cancelled = client.post(f'/api/v1/fulfillment/cases/{case_id}/cancel', json={})
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()['state'] == 'CANCELLED'
        assert cancelled.json()['state_json']['cancellation']['refund_executed'] is False


def test_operator_create_and_notifications_use_authenticated_tenant(monkeypatch):
    from src.app.services.fulfillment import notifications
    key = 'tenant-create-key'
    tenant = 'create-' + uuid.uuid4().hex
    monkeypatch.setenv('OWNER_API_KEY', key)
    monkeypatch.setenv('OPERATOR_TENANT_MEMBERSHIP_MODE', 'strict')
    with db_session() as db:
        grant_membership(db, principal_hash=principal_hash_for_api_key(key), tenant_id=tenant,
                         role='owner', auth_method='api_key', created_by='fixture')
        foreign = notifications.notify(db, kind='fixture', summary='PRIVATE_NOTIFICATION_CANARY', tenant_id='default')
        own = notifications.notify(db, kind='fixture', summary='Owned note', tenant_id=tenant)
        db.commit()
    with TestClient(create_app(), headers={'x-api-key': key, 'x-tenant-id': tenant}) as client:
        created = client.post('/api/v1/fulfillment/cases', json={})
        assert created.status_code == 200, created.text
        cid = created.json()['case_id']
        assert client.get(f'/api/v1/fulfillment/cases/{cid}/operator-view').status_code == 200
        feed = client.get('/api/v1/fulfillment/notifications')
        assert feed.status_code == 200
        assert 'PRIVATE_NOTIFICATION_CANARY' not in feed.text
        assert 'Owned note' in feed.text
        marked = client.post('/api/v1/fulfillment/notifications/seen', json={'ids': [own, foreign]})
        assert marked.status_code == 200
        assert marked.json()['marked'] == 1
    with db_session() as db:
        assert repository.current_version(db, cid, tenant) is not None
        assert any(n['id'] == foreign for n in notifications.list_notifications(db, tenant_id='default', unseen_only=True))
