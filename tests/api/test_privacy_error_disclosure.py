"""Real database failures cannot export private SQL parameters through error paths."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from src.app.deps import get_redis
from src.app.models.request_database_middleware import RequestDatabaseOwnerMiddleware
from src.app.models.database_ownership import database_owner
from src.app.models.db import db_session
from src.app.routers import privacy
from tests.buyer_identity_helpers import install_tenant_context
from tests.privacy_store_fakes import SharedStore


SUBJECT = 'PRIVATE-SUBJECT-CANARY-NOT-FOR-ERROR-OUTPUT'


@pytest.fixture
def failing_privacy_client(tmp_path, monkeypatch):
    monkeypatch.setenv('OWNER_API_KEY', 'isolated-privacy-error-owner')
    engine = create_engine('sqlite:///' + str(tmp_path / 'privacy-errors.sqlite3'))
    # Preserve the normal compatibility bootstrap, then use real database
    # constraints to reject the two writes. No route/session helper is replaced.
    with engine.begin() as db:
        db.execute(text('CREATE TABLE decision_logs(id TEXT, tenant_id TEXT, input_data TEXT, valid_from TEXT, '
            'agent_name TEXT, retrieved_context TEXT, agent_reasoning TEXT, proposed_action TEXT, '
            'policy_version TEXT, approval_required INTEGER, execution_status TEXT)'))
        db.execute(text('CREATE TABLE privacy_deletion_job(id TEXT PRIMARY KEY, tenant_id TEXT, '
            'subject_hash TEXT, status TEXT, stages_json TEXT, action_required_json TEXT, '
            'created_at TEXT, updated_at TEXT)'))
    with database_owner(engine):
        with db_session() as db:
            db.execute(text('SELECT 1'))
    with engine.begin() as db:
        db.execute(text('INSERT INTO customers(id,email,name,phone,tenant_id,tenant_ownership_status) '
                        'VALUES (:uid,:email,:name,:phone,:tenant,:ownership)'),
                   {'uid':SUBJECT,'email':'private-canary@example.test','name':'Private Buyer',
                    'phone':'private-phone-canary','tenant':'controller-a','ownership':'authenticated_request_context'})
        db.execute(text('INSERT INTO chat_messages(id,tenant_id,uid,session_id,session_epoch,role,content,trace_id) '
                        'VALUES (:id,:tenant,:uid,:session,:epoch,:role,:content,:trace)'),
                   {'id':'private-message','tenant':'controller-a','uid':SUBJECT,'session':'private-session',
                    'epoch':'private-epoch','role':'user','content':'private message','trace':'private-trace'})
        db.execute(text("CREATE TRIGGER reject_private_chat_delete BEFORE DELETE ON chat_messages "
                        "BEGIN SELECT RAISE(ABORT,'owned privacy store unavailable'); END"))
        db.execute(text("CREATE TRIGGER reject_private_customer_redaction BEFORE UPDATE ON customers "
                        "BEGIN SELECT RAISE(ABORT,'owned privacy store unavailable'); END"))
    app = FastAPI()
    app.state.engine = engine
    install_tenant_context(app)
    app.add_middleware(RequestDatabaseOwnerMiddleware)
    app.include_router(privacy.router)
    store = SharedStore()
    app.dependency_overrides[get_redis] = lambda: store
    client = TestClient(app, headers={'x-api-key': 'isolated-privacy-error-owner',
                                     'x-tenant-id': 'controller-a'}, raise_server_exceptions=False)
    try:
        yield client, engine
    finally:
        client.close()
        engine.dispose()


@pytest.mark.parametrize('method,path,code', [
    ('DELETE', 'data', 'privacy_erasure_failed'),
    ('POST', 'redact', 'privacy_redaction_failed'),
])
def test_private_database_parameters_are_absent_from_privacy_http_errors(
    failing_privacy_client, method, path, code,
):
    client, _ = failing_privacy_client
    response = client.request(method, f'/api/v1/privacy/{path}/{SUBJECT}')
    assert response.status_code == 500
    assert SUBJECT not in response.text
    assert '[SQL:' not in response.text
    assert 'parameters:' not in response.text
    assert response.json() == {'detail': code}


def test_failed_erasure_job_keeps_only_a_generic_reason_and_subject_hash(failing_privacy_client):
    client, engine = failing_privacy_client
    response = client.delete(f'/api/v1/privacy/data/{SUBJECT}')
    assert response.status_code == 500
    with engine.connect() as db:
        row = db.execute(text('SELECT id,subject_hash,stages_json FROM privacy_deletion_job')).one()
    assert SUBJECT not in json.dumps(list(row))
    assert json.loads(row.stages_json) == {'tenant_scoped_database': {
        'status': 'failed', 'error_code': 'privacy_database_operation_failed',
    }}
    job = client.get(f'/api/v1/privacy/deletion-jobs/{row.id}')
    assert job.status_code == 200
    assert job.json()['status'] == 'failed'
    assert SUBJECT not in job.text
    assert '[SQL:' not in job.text
    foreign = client.get(f'/api/v1/privacy/deletion-jobs/{row.id}',
                         headers={'x-tenant-id': 'controller-b'})
    assert foreign.status_code == 404


def test_missing_operator_credentials_still_deny_before_data_access(failing_privacy_client):
    client, engine = failing_privacy_client
    client.headers.pop('x-api-key')
    response = client.delete(f'/api/v1/privacy/data/{SUBJECT}')
    assert response.status_code == 401
    with engine.connect() as db:
        assert db.scalar(text('SELECT count(*) FROM privacy_deletion_job')) == 0


def test_export_keeps_the_existing_policy_denial_ahead_of_database_access(failing_privacy_client):
    client, _ = failing_privacy_client
    response = client.get(f'/api/v1/privacy/export/{SUBJECT}')
    assert response.status_code == 403
    assert response.json()['detail']['error'] == 'policy_gate_denied'
    assert '[SQL:' not in response.text
