"""Decision identity and write success describe the actual durable record."""
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.models.db import create_runtime_engine
from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
from src.app.services import decision_log


@pytest.fixture
def owned_log(tmp_path, monkeypatch):
    engine = create_runtime_engine(f"sqlite+pysqlite:///{tmp_path/'owned-log.sqlite3'}")
    with engine.begin() as db:
        db.execute(text('''CREATE TABLE decision_logs (
            id TEXT PRIMARY KEY, tenant_id TEXT, agent_name TEXT,
            valid_from TEXT, valid_to TEXT, system_from TEXT, system_to TEXT,
            input_data TEXT, retrieved_context TEXT, agent_reasoning TEXT,
            proposed_action TEXT, policy_version TEXT, approval_required BOOLEAN,
            execution_status TEXT)'''))

    @contextmanager
    def sessions():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr(decision_log, 'db_session', sessions)
    monkeypatch.setattr(decision_log, 'telemetry_emit', lambda *a, **kw: None)
    monkeypatch.setattr(decision_log.PolicyEvaluator, 'evaluate_and_persist', lambda *a, **kw: None)
    monkeypatch.delenv('HUMAN_ESCALATION_WEBHOOK_URL', raising=False)
    monkeypatch.setenv('RAGAS_EVAL_ENABLED', '0')
    token = set_active_tenant_id('tenant-a')
    try:
        yield engine
    finally:
        reset_active_tenant_id(token)
        engine.dispose()


def write(identity='trace-a', tenant='tenant-a', **changes):
    return decision_log.log_decision(agent_name='test', input_data={}, retrieved_context={},
        proposed_action={}, decision_id=identity, tenant_id=tenant, **changes)


def test_same_tenant_retry_keeps_one_durable_decision(owned_log):
    assert write() == write() == 'trace-a'
    with owned_log.connect() as db:
        assert db.scalar(text('SELECT count(*) FROM decision_logs')) == 1


def test_existing_foreign_identity_cannot_report_write_success(owned_log):
    assert write() == 'trace-a'
    assert write(tenant='tenant-b') is None
    with owned_log.connect() as db:
        assert db.execute(text('SELECT id,tenant_id FROM decision_logs')).all() == [('trace-a','tenant-a')]


@pytest.mark.parametrize('record_tenant', ['tenant-a', 'tenant-b', None])
def test_close_validity_only_changes_current_tenant_history(owned_log, record_tenant):
    with owned_log.begin() as db:
        db.execute(text("INSERT INTO decision_logs(id,tenant_id,valid_to,system_to) VALUES ('old',:tenant,'infinity','infinity')"),
                   {'tenant':record_tenant})
    changed = decision_log.close_decision_validity('old', valid_to='closed', system_to='closed')
    assert changed is (record_tenant == 'tenant-a')
    with owned_log.connect() as db:
        assert db.execute(text("SELECT valid_to,system_to FROM decision_logs WHERE id='old'")).one() == (
            ('closed','closed') if record_tenant == 'tenant-a' else ('infinity','infinity'))


def test_superseding_another_tenants_id_preserves_its_history(owned_log):
    assert write('foreign', 'tenant-b') == 'foreign'
    assert write('new', supersedes_decision_id='foreign') == 'new'
    with owned_log.connect() as db:
        assert db.execute(text("SELECT valid_to,system_to FROM decision_logs WHERE id='foreign'")).one() == ('infinity','infinity')


@pytest.mark.parametrize('failure', ['insert', 'commit'])
def test_failed_storage_does_not_report_success_or_evaluate_policy(owned_log, monkeypatch, failure):
    calls = []

    class FailingSession(Session):
        def execute(self, statement, *args, **kwargs):
            if failure == 'insert' and str(statement).lstrip().upper().startswith('INSERT'):
                raise RuntimeError('owned-insert-unavailable')
            return super().execute(statement, *args, **kwargs)

        def commit(self):
            if failure == 'commit':
                raise RuntimeError('owned-commit-unavailable')
            return super().commit()

    @contextmanager
    def sessions():
        with FailingSession(owned_log) as db:
            yield db

    monkeypatch.setattr(decision_log, 'db_session', sessions)
    monkeypatch.setattr(decision_log.PolicyEvaluator, 'evaluate_and_persist', lambda *a, **kw: calls.append(kw))
    assert write() is None
    assert calls == []
    with owned_log.connect() as db:
        assert db.scalar(text('SELECT count(*) FROM decision_logs')) == 0


@pytest.mark.parametrize('failure', ['insert', 'commit'])
def test_failed_replacement_leaves_prior_decision_open(owned_log, monkeypatch, failure):
    assert write('prior') == 'prior'

    class FailingReplacement(Session):
        def execute(self, statement, *args, **kwargs):
            if failure == 'insert' and str(statement).lstrip().upper().startswith('INSERT'):
                raise RuntimeError('owned-replacement-insert-unavailable')
            return super().execute(statement, *args, **kwargs)

        def commit(self):
            if failure == 'commit' and self.scalar(text("SELECT count(*) FROM decision_logs WHERE id='replacement'")):
                raise RuntimeError('owned-replacement-commit-unavailable')
            return super().commit()

    @contextmanager
    def sessions():
        with FailingReplacement(owned_log) as db:
            yield db

    monkeypatch.setattr(decision_log, 'db_session', sessions)
    assert write('replacement', supersedes_decision_id='prior') is None
    with owned_log.connect() as db:
        assert db.execute(text('SELECT id,valid_to,system_to FROM decision_logs')).all() == [('prior','infinity','infinity')]


def test_successful_replacement_closes_prior_in_same_transaction(owned_log):
    assert write('prior') == 'prior'
    assert write('replacement', supersedes_decision_id='prior') == 'replacement'
    with owned_log.connect() as db:
        rows = {r[0]:r[1:] for r in db.execute(text('SELECT id,valid_to,system_to FROM decision_logs'))}
        assert set(rows) == {'prior','replacement'}
        assert rows['prior'][0] != 'infinity' and rows['prior'][1] != 'infinity'
        assert rows['replacement'] == ('infinity','infinity')


def test_replayed_identity_cannot_close_newly_supplied_history(owned_log):
    assert write('existing') == 'existing'
    assert write('prior') == 'prior'
    assert write('existing', supersedes_decision_id='prior') == 'existing'
    with owned_log.connect() as db:
        assert db.execute(text("SELECT valid_to,system_to FROM decision_logs WHERE id='prior'")).one() == ('infinity','infinity')


def test_close_validity_reports_commit_failure(owned_log, monkeypatch):
    assert write('prior') == 'prior'

    class CannotCommit(Session):
        def commit(self):
            raise RuntimeError('owned-close-commit-unavailable')

    @contextmanager
    def sessions():
        with CannotCommit(owned_log) as db:
            yield db

    monkeypatch.setattr(decision_log, 'db_session', sessions)
    assert decision_log.close_decision_validity('prior') is False
    with owned_log.connect() as db:
        assert db.execute(text("SELECT valid_to,system_to FROM decision_logs WHERE id='prior'")).one() == ('infinity','infinity')
