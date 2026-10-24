"""Owner role does not grant access to another tenant's supplier evidence."""
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import text
from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services.operator_tenant_membership import grant_membership, principal_hash_for_api_key


def test_inbound_evidence_jobs_and_replay_are_tenant_scoped(monkeypatch):
    key = 'inbound-scope-key'
    tenant = 'inbound-' + uuid.uuid4().hex
    foreign, own = uuid.uuid4().hex, uuid.uuid4().hex
    monkeypatch.setenv('OWNER_API_KEY', key)
    monkeypatch.setenv('OPERATOR_TENANT_MEMBERSHIP_MODE', 'strict')
    calls = []
    def load(db, **kwargs):
        calls.append(kwargs)
        return {'text': 'owned supplier evidence'}
    monkeypatch.setattr('src.app.services.inbound_email_evidence.load_raw_evidence', load)
    with db_session() as db:
        grant_membership(db, principal_hash=principal_hash_for_api_key(key), tenant_id=tenant,
                         role='owner', auth_method='api_key', created_by='fixture')
        for ident, scope in [(foreign, 'default'), (own, tenant)]:
            db.execute(text('''INSERT INTO inbound_email_inbox
                (id,tenant_id,provider,provider_message_id,status,sanitized_payload_json,
                 raw_evidence_ref,enrichment_status,enrichment_error)
                VALUES (:id,:tenant,'fixture',:id,'received','{}',:ref,'dead_lettered',:error)'''),
                {'id': ident, 'tenant': scope, 'ref': 'fixture:'+ident,
                 'error': 'PRIVATE_EMAIL_CANARY' if scope == 'default' else 'owned error'})
        db.commit()
    with TestClient(create_app(), headers={'x-api-key':key,'x-tenant-id':tenant}) as client:
        for path, body in [
            (f'/email/inbox/{foreign}/evidence/read', {'purpose':'review'}),
            (f'/email/inbox/{foreign}/evidence/legal-hold', {'purpose':'review','enabled':True}),
            (f'/email/enrichment/jobs/{foreign}/replay', {'purpose':'review'}),
        ]:
            response = client.post('/api/v1/fulfillment'+path, json=body)
            assert response.status_code == 404, response.text
        assert calls == []
        allowed = client.post(f'/api/v1/fulfillment/email/inbox/{own}/evidence/read', json={'purpose':'review'})
        assert allowed.status_code == 200, allowed.text
        assert calls[0]['tenant_id'] == tenant
        for suffix in ['', '?status=dead_lettered']:
            jobs = client.get('/api/v1/fulfillment/email/enrichment/jobs'+suffix)
            assert jobs.status_code == 200
            assert 'PRIVATE_EMAIL_CANARY' not in jobs.text
            assert {row['inbox_id'] for row in jobs.json()['jobs']} == {own}
    with db_session() as db:
        assert db.execute(text('SELECT enrichment_status FROM inbound_email_inbox WHERE id=:id'),
                          {'id':foreign}).scalar_one() == 'dead_lettered'
