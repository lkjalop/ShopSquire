from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services import outbound_email_monitor as monitor
from src.app.services.operator_tenant_membership import grant_membership, principal_hash_for_api_key


def test_authenticated_outbound_reader_and_simulator_cannot_cross_tenants(monkeypatch):
    key = 'outbound-scope-test-key'
    tenant = 'outbound-' + uuid4().hex
    foreign = tenant + '-foreign'
    monkeypatch.setenv('OWNER_API_KEY', key)
    monkeypatch.setenv('OPERATOR_TENANT_MEMBERSHIP_MODE', 'strict')
    monitor._ensure_tables()
    with db_session() as db:
        grant_membership(db, principal_hash=principal_hash_for_api_key(key), tenant_id=tenant,
                         role='owner', auth_method='api_key', created_by='test-fixture')
        for scope in (tenant, foreign):
            db.execute(text('''INSERT INTO outbound_email_anomalies
                (id,event_id,tenant_id,agent_id,severity,reasons_json,score,created_at)
                VALUES (:id,:id,:scope,'same-agent','high',:reasons,1,1)'''),
                dict(id=uuid4().hex, scope=scope, reasons='["'+scope+'-CANARY"]'))
        db.commit()
    with TestClient(create_app(), headers={'x-api-key':key, 'x-tenant-id':tenant}) as client:
        response = client.get('/api/v1/admin/email_security/outbound/anomalies')
        assert response.status_code == 200, response.text
        assert {item['tenant_id'] for item in response.json()['items']} == {tenant}
        assert response.json()['count'] == len(response.json()['items'])
        assert foreign + '-CANARY' not in response.text
        assert client.get('/api/v1/admin/email_security/outbound/anomalies',
                          headers={'x-tenant-id':foreign}).status_code == 403
        assert client.post('/api/v1/admin/email_security/outbound/simulate',
                           json={'tenant_id':foreign, 'count':1}).status_code == 403
        @contextmanager
        def unavailable():
            raise ConnectionError('offline')
            yield
        monkeypatch.setattr(monitor, 'db_session', unavailable)
        failed = client.get('/api/v1/admin/email_security/outbound/anomalies')
        assert failed.status_code == 503
        assert failed.json()['detail'] == 'outbound_monitor_unavailable'
