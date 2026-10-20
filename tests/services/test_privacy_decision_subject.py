"""Privacy operations must use the owning subject, never a fuzzy JSON match."""
from contextlib import contextmanager
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.deps import hash_uid
from src.app.routers import privacy


@pytest.fixture
def decision_store(monkeypatch):
    engine = create_engine('sqlite://')
    statements = [
        'CREATE TABLE decision_logs (id TEXT PRIMARY KEY, tenant_id TEXT, input_data TEXT, agent_name TEXT, valid_from TEXT, retrieved_context TEXT, agent_reasoning TEXT, proposed_action TEXT, policy_version TEXT, approval_required INTEGER, execution_status TEXT)',
        'CREATE TABLE decision_audits (id TEXT, decision_id TEXT, action TEXT, actor TEXT, metadata TEXT, created_at TEXT)',
        'CREATE TABLE chat_messages (id TEXT, tenant_id TEXT, uid TEXT, session_id TEXT, session_epoch TEXT, role TEXT, content TEXT, trace_id TEXT, created_at TEXT)',
        'CREATE TABLE conversation_fact_observation (tenant_id TEXT, subject_ref TEXT)',
        'CREATE TABLE draft_orders (customer_id TEXT, tenant_id TEXT)',
        'CREATE TABLE customers (id TEXT, tenant_id TEXT)',
        'CREATE TABLE orders (id TEXT, customer_id TEXT, tenant_id TEXT)',
        'CREATE TABLE order_sessions (uid TEXT, tenant_id TEXT, order_id TEXT)',
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(privacy, 'db_session', sessions)
    monkeypatch.setattr(privacy, '_ct', lambda: 'controller-a')
    monkeypatch.setattr(privacy, 'enforce_action_authority', lambda *args, **kwargs: None)
    monkeypatch.setattr(privacy, 'dlp_sanitize_export_value', lambda value: (value, []))
    import src.app.services.privacy_deletion_orchestrator as jobs
    import src.app.services.user_data_inventory as inventory
    import src.app.services.legacy_commerce_tenant_ownership as legacy
    monkeypatch.setattr(jobs, 'start_job', lambda **kwargs: 'owned-test-job')
    monkeypatch.setattr(jobs, 'finish_job', lambda *args, **kwargs: {'status': 'completed'})
    monkeypatch.setattr(inventory, 'erase_redis', lambda *args: {'complete': True})
    monkeypatch.setattr(inventory, 'export_redis', lambda *args: {})
    monkeypatch.setattr(legacy, 'erase_authoritatively_owned_subject_rows',
                        lambda *args, **kwargs: {'deleted': {}, 'unclassified': {}})
    yield engine
    engine.dispose()


@pytest.mark.parametrize('uid', ['buyer_7', 'buyer%7', 'buyer!7', 'buyer"7', 'buyer\\7', 'buyer\u00e9'])
@pytest.mark.parametrize('operation', ['export', 'delete'])
def test_privacy_decisions_are_owned_by_exact_top_level_subject(decision_store, uid, operation):
    records = {
        'owned-spaced': ('controller-a', json.dumps({'uid': uid})),
        'owned-formatted': ('controller-a', json.dumps({'uid': uid}, indent=2, ensure_ascii=False)),
        'owned-hash': ('controller-a', json.dumps({'uid_hash': hash_uid(uid)})),
        'different-subject': ('controller-a', json.dumps({'uid': uid.replace('_', 'X').replace('%', 'XYZ') + '-other'})),
        'wildcard-victim': ('controller-a', json.dumps({'uid': uid.replace('_', 'X').replace('%', 'XYZ')})),
        'nested-unowned': ('controller-a', json.dumps({'uid': 'someone-else', 'quoted': {'uid': uid}})),
        'conflicting-owner': ('controller-a', json.dumps({'uid': 'someone-else', 'uid_hash': hash_uid(uid)})),
        'foreign-controller': ('controller-b', json.dumps({'uid': uid})),
        'malformed': ('controller-a', '{not-json'),
    }
    # The control remains a different subject even when the ID has no wildcard.
    if records['wildcard-victim'][1] == records['owned-spaced'][1]:
        records['wildcard-victim'] = ('controller-a', json.dumps({'uid': uid + '-other'}))
    with decision_store.begin() as connection:
        for key, (tenant, payload) in records.items():
            connection.execute(text('INSERT INTO decision_logs (id,tenant_id,input_data) VALUES (:id,:tenant,:payload)'),
                               {'id': key, 'tenant': tenant, 'payload': payload})
            connection.execute(text('INSERT INTO decision_audits (id,decision_id) VALUES (:id,:id)'), {'id': key})
    owned = {'owned-spaced', 'owned-formatted', 'owned-hash'}
    if operation == 'export':
        result = privacy.export_user_data(uid, object(), False, 'owner')
        assert {row['id'] for row in result['decision_logs']} == owned
        assert {row['id'] for row in result['decision_audits']} == owned
    else:
        result = privacy.delete_user_data(uid, object(), 'owner')
        assert result['deleted_records']['decision_logs'] == len(owned)
        with decision_store.connect() as connection:
            assert set(connection.execute(text('SELECT id FROM decision_logs')).scalars()) == set(records) - owned
            assert set(connection.execute(text('SELECT id FROM decision_audits')).scalars()) == set(records) - owned
