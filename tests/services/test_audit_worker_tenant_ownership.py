"""Durable worker identity must agree with its exact tenant/trace record."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest
from sqlalchemy.orm import Session

from src.app.models.db import create_runtime_engine
from src.app.models.orm import RecommendationAuditOutboxRecord
from src.app.platform.tenant_context import current_tenant_id, reset_active_tenant_id, set_active_tenant_id
from src.app.services import recommendation_audit_outbox as outbox


@pytest.fixture
def owned_audits(tmp_path, monkeypatch):
    engine = create_runtime_engine(f"sqlite+pysqlite:///{tmp_path/'owned-audits.sqlite3'}")
    RecommendationAuditOutboxRecord.__table__.create(engine)

    @contextmanager
    def sessions():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr('src.app.models.db.db_session', sessions)
    monkeypatch.setattr('src.app.workers.task_runner.submit_task', lambda *a, **kw: 'owned-task')
    token = set_active_tenant_id('ambient-foreign')
    try:
        yield engine
    finally:
        reset_active_tenant_id(token)
        engine.dispose()


def queued(tenant='tenant-a', trace='trace-a', **changes):
    payload = dict(tenant_id=tenant, decision_id=trace, agent_name='test', input_data={},
                   retrieved_context={}, proposed_action={})
    record = outbox.enqueue_recommendation_audit(tenant_id=tenant, trace_id=trace,
                                                payload={**payload, **changes})
    return dict(tenant_id=tenant, outbox_id=record['outbox_id'])


@pytest.mark.parametrize('outcome', ['success', 'retry', 'process_loss'])
def test_worker_binds_record_tenant_and_restores_caller_on_every_exit(owned_audits, monkeypatch, outcome):
    job = queued()

    class ProcessLost(BaseException):
        pass

    def writer(**payload):
        assert current_tenant_id() == payload['tenant_id'] == 'tenant-a'
        if outcome == 'retry':
            raise RuntimeError('owned-store-unavailable')
        if outcome == 'process_loss':
            raise ProcessLost()
        return payload['decision_id']

    monkeypatch.setattr('src.app.services.decision_log.log_decision', writer)
    if outcome == 'success':
        outbox.execute_recommendation_audit_job(job)
    else:
        with pytest.raises(RuntimeError if outcome == 'retry' else ProcessLost):
            outbox.execute_recommendation_audit_job(job)
    assert current_tenant_id() == 'ambient-foreign'
    with Session(owned_audits) as db:
        row = db.get(RecommendationAuditOutboxRecord, job['outbox_id'])
        assert row.status == {'success':'completed', 'retry':'retry', 'process_loss':'running'}[outcome]
        assert row.attempts == 1


@pytest.mark.parametrize('changed', [{'tenant_id':'tenant-b'}, {'decision_id':'foreign-trace'}])
def test_worker_rejects_payload_that_disagrees_with_durable_identity(owned_audits, monkeypatch, changed):
    job = queued(**changed)
    calls = []
    monkeypatch.setattr('src.app.services.decision_log.log_decision', lambda **p: calls.append(p) or p['decision_id'])
    with pytest.raises(ValueError, match='payload_identity_mismatch'):
        outbox.execute_recommendation_audit_job(job)
    assert calls == []
    assert current_tenant_id() == 'ambient-foreign'
    with Session(owned_audits) as db:
        row = db.get(RecommendationAuditOutboxRecord, job['outbox_id'])
        assert row.status == 'retry'
        assert row.error_code == 'ValueError'


def test_wrong_tenant_job_cannot_claim_owned_record(owned_audits, monkeypatch):
    job = queued()
    calls = []
    monkeypatch.setattr('src.app.services.decision_log.log_decision', lambda **p: calls.append(p))
    outbox.execute_recommendation_audit_job({**job, 'tenant_id':'tenant-b'})
    assert calls == [] and current_tenant_id() == 'ambient-foreign'
    with Session(owned_audits) as db:
        row = db.get(RecommendationAuditOutboxRecord, job['outbox_id'])
        assert row.status == 'queued' and row.attempts == 0


def test_nested_workers_restore_each_record_owner(owned_audits, monkeypatch):
    outer, inner = queued(), queued('tenant-b', 'trace-b')
    owners = []

    def writer(**payload):
        owners.append(current_tenant_id())
        assert current_tenant_id() == payload['tenant_id']
        if payload['tenant_id'] == 'tenant-a':
            outbox.execute_recommendation_audit_job(inner)
            assert current_tenant_id() == 'tenant-a'
        return payload['decision_id']

    monkeypatch.setattr('src.app.services.decision_log.log_decision', writer)
    outbox.execute_recommendation_audit_job(outer)
    assert owners == ['tenant-a', 'tenant-b']
    assert current_tenant_id() == 'ambient-foreign'


def test_parallel_workers_keep_tenants_separate(owned_audits, monkeypatch):
    jobs = [queued(), queued('tenant-b', 'trace-b')]
    barrier = Barrier(2)

    def writer(**payload):
        barrier.wait(timeout=10)
        assert current_tenant_id() == payload['tenant_id']
        return payload['decision_id']

    def worker(job):
        token = set_active_tenant_id('thread-caller')
        try:
            outbox.execute_recommendation_audit_job(job)
            assert current_tenant_id() == 'thread-caller'
        finally:
            reset_active_tenant_id(token)

    monkeypatch.setattr('src.app.services.decision_log.log_decision', writer)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(worker, jobs))
    assert current_tenant_id() == 'ambient-foreign'
    with Session(owned_audits) as db:
        assert [db.get(RecommendationAuditOutboxRecord, job['outbox_id']).status for job in jobs] == ['completed','completed']
