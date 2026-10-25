"""Real database contracts; each test owns only its generated schema/role."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session


@pytest.fixture
def pg():
    url = os.getenv('TEST_POSTGRES_URL')
    if not url:
        pytest.skip('TEST_POSTGRES_URL is required')
    admin = create_engine(url)
    assert admin.dialect.name == 'postgresql'
    name = 'release_' + uuid.uuid4().hex[:12]
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{name}"'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={name}'}, pool_size=5)
    try:
        yield engine, name, admin
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        admin.dispose()


def test_dmarc_postgres_ownership_and_weighted_summary(pg, monkeypatch):
    from src.app.services import dmarc_ingest
    from tests.security.test_dmarc_boundaries import xml
    engine, _, _ = pg
    monkeypatch.setattr(dmarc_ingest, 'get_engine', lambda: engine)
    dmarc_ingest.ingest_aggregate(xml('tenant-a.example'), tenant_id='a')
    dmarc_ingest.ingest_aggregate(xml('tenant-b.example', count=900), tenant_id='b')
    result = dmarc_ingest.get_summary(1, tenant_id='a', now=100001)
    assert result['fail_rate'] == 1
    assert [row[0] for row in result['top_domains']] == ['tenant-a.example']


def test_transaction_tenant_binding_survives_commit_and_pool_reuse(pg):
    from src.app.platform.tenant_session import bind_session_tenant
    engine, schema, admin = pg
    role = schema + '_reader'
    with engine.begin() as db:
        db.execute(text('CREATE TABLE guarded (tenant_id TEXT, value TEXT)'))
        db.execute(text("INSERT INTO guarded VALUES ('a','A'), ('b','B'), (NULL,'unowned')"))
        db.execute(text('ALTER TABLE guarded ENABLE ROW LEVEL SECURITY'))
        db.execute(text("CREATE POLICY tenants ON guarded USING (tenant_id = NULLIF(current_setting('app.current_tenant', true), ''))"))
        db.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        db.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
        db.execute(text(f'GRANT SELECT ON guarded TO "{role}"'))
    restricted = create_engine(str(engine.url.render_as_string(hide_password=False)),
        connect_args={'options': f'-csearch_path={schema}'}, pool_size=1, max_overflow=0)
    @event.listens_for(restricted, 'connect')
    def use_role(connection, record):
        with connection.cursor() as cursor:
            cursor.execute(f'SET ROLE "{role}"')
        connection.commit()
    try:
        pids = []
        for tenant, expected in [('a', 'A'), ('b', 'B')]:
            with Session(restricted) as db:
                bind_session_tenant(db, tenant_id=tenant)
                pids.append(db.execute(text('SELECT pg_backend_pid()')).scalar())
                assert db.execute(text('SELECT value FROM guarded')).scalars().all() == [expected]
                db.commit()
                assert db.execute(text('SELECT value FROM guarded')).scalars().all() == [expected]
        assert len(set(pids)) == 1
        with Session(restricted) as db:
            assert db.execute(text('SELECT value FROM guarded')).scalars().all() == []
    finally:
        restricted.dispose()
        with engine.begin() as db:
            db.execute(text(f'DROP OWNED BY "{role}"'))
            db.execute(text(f'DROP ROLE "{role}"'))


def test_category_cap_serializes_across_internal_commits(pg):
    from src.app.services.fulfillment.category_budget_lock import category_budget_lock
    engine, _, _ = pg
    with engine.begin() as db:
        db.execute(text('CREATE TABLE approved (id TEXT PRIMARY KEY, tenant_id TEXT, category TEXT, spend BIGINT)'))
    barrier = threading.Barrier(2)
    def approve(case_id):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            with category_budget_lock(db, tenant_id='a', category='it'):
                spent = db.execute(text("SELECT COALESCE(SUM(spend),0) FROM approved WHERE tenant_id='a' AND category='it'")).scalar()
                if spent + 600 > 1000:
                    return False
                db.execute(text("INSERT INTO approved VALUES (:id,'a','it',600)"), {'id': case_id})
                db.commit()  # Workflow-owned commit must not release the category guard.
                return True
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(approve, case_id) for case_id in ('one', 'two')]
        assert sorted(f.result(timeout=20) for f in futures) == [False, True]
    with engine.connect() as db:
        assert db.execute(text('SELECT SUM(spend) FROM approved')).scalar() == 600


def test_actual_evaluation_migration_preserves_legacy_scores_as_unverified(pg):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    engine, _, _ = pg
    spec = importlib.util.spec_from_file_location('repair_migration',
        Path(__file__).resolve().parents[2] / 'alembic/versions/20260875_evaluation_tenant_integrity.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as db:
        db.execute(text('CREATE TABLE decision_logs (id TEXT PRIMARY KEY, tenant_id TEXT)'))
        db.execute(text("INSERT INTO decision_logs VALUES ('d','a')"))
        db.execute(text('CREATE TABLE security_events (tenant_id TEXT)'))
        db.execute(text('CREATE TABLE incidents (tenant_id TEXT)'))
        db.execute(text('CREATE TABLE ragas_baseline (id TEXT PRIMARY KEY, baseline_score FLOAT)'))
        db.execute(text('CREATE TABLE ragas_eval_results (eval_id TEXT, decision_log_id TEXT, created_at TIMESTAMP, faithfulness FLOAT)'))
        db.execute(text("INSERT INTO ragas_eval_results VALUES ('e','d',now(),0.99)"))
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        assert tuple(db.execute(text('SELECT tenant_id, evaluation_status, faithfulness FROM ragas_eval_results')).one()) == ('a', 'legacy_unverified', .99)
        policies = db.execute(text("SELECT qual, with_check FROM pg_policies WHERE schemaname=current_schema()")).all()
        assert len(policies) == 3
        assert all('NULLIF' in row[0] and 'NULLIF' in row[1] for row in policies)


def test_audit_recovery_replays_crash_after_durable_decision_once(pg, monkeypatch):
    from src.app.models.orm import RecommendationAuditOutboxRecord
    from src.app.services import recommendation_audit_outbox as outbox
    from src.app.platform.tenant_context import current_tenant_id
    from datetime import datetime, timedelta, timezone
    engine, _, _ = pg
    RecommendationAuditOutboxRecord.__table__.create(engine)
    with engine.begin() as db:
        db.execute(text('''CREATE TABLE decision_logs (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, agent_name TEXT,
            valid_from TIMESTAMP, valid_to TIMESTAMP, system_from TIMESTAMP, system_to TIMESTAMP,
            input_data TEXT, retrieved_context TEXT, agent_reasoning TEXT, proposed_action TEXT,
            policy_version TEXT, approval_required BOOLEAN, execution_status TEXT)'''))
    @contextmanager
    def session():
        with Session(engine) as db:
            yield db
    monkeypatch.setattr('src.app.models.db.db_session', session)
    from src.app.services import decision_log
    monkeypatch.setattr(decision_log, 'db_session', session)
    monkeypatch.setattr(decision_log, 'telemetry_emit', lambda *a, **kw: None)
    monkeypatch.setattr(decision_log.PolicyEvaluator, 'evaluate_and_persist', lambda *a, **kw: None)
    monkeypatch.delenv('HUMAN_ESCALATION_WEBHOOK_URL', raising=False)
    monkeypatch.setenv('RAGAS_EVAL_ENABLED', '0')
    real_writer = decision_log.log_decision
    monkeypatch.setattr('src.app.workers.task_runner.submit_task', lambda *a, **kw: 'test-task')
    queued = outbox.enqueue_recommendation_audit(tenant_id='a', trace_id='trace',
        payload={'tenant_id': 'a', 'decision_id': 'trace', 'agent_name': 'test',
                 'input_data': {}, 'retrieved_context': {}, 'proposed_action': {}})
    class ProcessDied(BaseException):
        pass
    def crash_after_commit(**payload):
        assert current_tenant_id() == 'a'
        assert real_writer(**payload) == payload['decision_id']
        raise ProcessDied()
    monkeypatch.setattr('src.app.services.decision_log.log_decision', crash_after_commit)
    job = {'tenant_id': 'a', 'outbox_id': queued['outbox_id']}
    with pytest.raises(ProcessDied):
        outbox.execute_recommendation_audit_job(job)
    with Session(engine) as db:
        row = db.get(RecommendationAuditOutboxRecord, queued['outbox_id'])
        row.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        assert row.status == 'running'
        db.commit()
    assert outbox.recover_pending_recommendation_audits() == 1
    def replay(**payload):
        return real_writer(**payload)
    monkeypatch.setattr('src.app.services.decision_log.log_decision', replay)
    outbox.execute_recommendation_audit_job(job)
    outbox.execute_recommendation_audit_job(job)
    with Session(engine) as db:
        assert db.get(RecommendationAuditOutboxRecord, queued['outbox_id']).status == 'completed'
        assert db.execute(text('SELECT COUNT(*) FROM decision_logs')).scalar() == 1
    assert real_writer(agent_name='test', input_data={}, retrieved_context={}, proposed_action={},
                       decision_id='trace', tenant_id='b') is None


def test_decision_columns_follow_resolved_table_across_search_paths(pg):
    from src.app.services.decision_log import _decision_log_columns

    engine, schema, admin = pg
    other_schema = schema + '_other'
    other = create_engine(engine.url, connect_args={'options': f'-csearch_path={other_schema}'})
    try:
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{other_schema}"'))
        with engine.begin() as db:
            db.execute(text('CREATE TABLE decision_logs (id TEXT, tenant_id TEXT NOT NULL)'))
        with other.begin() as db:
            db.execute(text('CREATE TABLE decision_logs (id TEXT, tenant_id TEXT NOT NULL, actor_id TEXT)'))
        with Session(other) as db:
            assert set(_decision_log_columns(db)) == {'id', 'tenant_id', 'actor_id'}
        with Session(engine) as db:
            assert set(_decision_log_columns(db)) == {'id', 'tenant_id'}
        with Session(other) as db:
            assert set(_decision_log_columns(db)) == {'id', 'tenant_id', 'actor_id'}
    finally:
        other.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA IF EXISTS "{other_schema}" CASCADE'))


def test_tenant_audit_insert_error_never_retries_without_ownership(pg, monkeypatch):
    from src.app.services import decision_log

    engine, _, _ = pg
    with engine.begin() as db:
        db.execute(text('''CREATE TABLE decision_logs (
            id TEXT PRIMARY KEY, tenant_id TEXT, agent_name TEXT, valid_from TIMESTAMP,
            input_data TEXT, proposed_action TEXT, policy_version TEXT,
            approval_required BOOLEAN, execution_status TEXT)'''))

    @contextmanager
    def session():
        with Session(engine) as db:
            yield db

    def fail_insert(*args):
        raise RuntimeError('owned_insert_fault')

    monkeypatch.setattr(decision_log, 'db_session', session)
    monkeypatch.setattr(decision_log, '_exec_decision_log_insert_mapped', fail_insert)
    result = decision_log.log_decision(agent_name='test', input_data={}, retrieved_context={},
                                      proposed_action={}, tenant_id='owned', decision_id='owned-fault')
    assert result is None
    with engine.connect() as db:
        assert db.scalar(text('SELECT COUNT(*) FROM decision_logs')) == 0
