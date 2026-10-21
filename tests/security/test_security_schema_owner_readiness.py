"""A ready schema belongs to its live database owner, not the whole process."""
import gc
import weakref

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect

from src.app.models.db import create_runtime_engine
from src.app.models.database_ownership import database_owner
from src.app.security import security_event_ingest as ingestion


@pytest.fixture(autouse=True)
def cold_schema_hint(monkeypatch):
    monkeypatch.setattr(ingestion, '_SECURITY_EVENT_TABLE_READY', False)
    monkeypatch.setattr(ingestion, '_ACTOR_STATE_TABLE_READY', False)


def initialize(table):
    if table == 'security_event_actor_state':
        return ingestion._ensure_actor_state_table()
    return ingestion.ensure_security_event_ingest_table()


@pytest.mark.parametrize('replacement', ['another_engine', 'replacement_pool'])
@pytest.mark.parametrize('table', ['security_event_ingest', 'security_event_actor_state'])
def test_each_new_owner_initializes_its_security_schema_without_global_reset(tmp_path, replacement, table):
    first = create_runtime_engine('sqlite://' if replacement == 'replacement_pool'
        else 'sqlite+pysqlite:///' + (tmp_path / 'first.sqlite3').as_posix())
    second = first
    try:
        with database_owner(first):
            initialize(table)
        assert inspect(first).has_table(table)
        if replacement == 'replacement_pool':
            first.dispose()
        else:
            second = create_runtime_engine('sqlite+pysqlite:///' + (tmp_path / 'second.sqlite3').as_posix())
        with database_owner(second):
            initialize(table)
        assert inspect(second).has_table(table), 'new_owner_skipped_security_schema_initialization'
    finally:
        first.dispose()
        if second is not first:
            second.dispose()


@pytest.mark.parametrize('table', ['security_event_ingest', 'security_event_actor_state'])
def test_failed_schema_initialization_remains_retryable(table):
    engine = create_runtime_engine('sqlite://')
    failures = []

    def fail_once(_conn, _cursor, statement, _parameters, _context, _many):
        if 'CREATE TABLE IF NOT EXISTS ' + table in statement and not failures:
            failures.append(True)
            raise RuntimeError('controlled_schema_initialization_failure')

    event.listen(engine, 'before_cursor_execute', fail_once)
    try:
        with database_owner(engine):
            initialize(table)
        assert failures == [True]
        assert not inspect(engine).has_table(table)
        with database_owner(engine):
            initialize(table)
        assert inspect(engine).has_table(table)
    finally:
        event.remove(engine, 'before_cursor_execute', fail_once)
        engine.dispose()


@pytest.mark.parametrize('table', ['security_event_ingest', 'security_event_actor_state'])
def test_schema_readiness_does_not_retain_a_discarded_database_owner(table):
    def build_and_release_owner():
        engine = create_runtime_engine('sqlite://')
        reference = weakref.ref(engine)
        with database_owner(engine):
            initialize(table)
        engine.dispose()
        return reference

    reference = build_and_release_owner()
    gc.collect()
    assert reference() is None


def test_failed_security_schema_is_reported_as_degraded_startup(monkeypatch, tmp_path):
    from src.app import main
    monkeypatch.setenv('DATABASE_URL', 'sqlite+pysqlite:///' + (tmp_path / 'startup.sqlite3').as_posix())
    monkeypatch.setenv('DATABASE_URL_RO', 'sqlite+pysqlite:///' + (tmp_path / 'startup.sqlite3').as_posix())
    monkeypatch.setenv('FEATURE_FLAGS_PATH', str(tmp_path / 'flags.json'))
    app = getattr(main, '_original_create_app', main.create_app)()
    engine = app.state.engine

    def reject_schema(_conn, _cursor, statement, _parameters, _context, _many):
        if 'CREATE TABLE IF NOT EXISTS security_event_ingest' in statement:
            raise RuntimeError('controlled_schema_initialization_failure')

    event.listen(engine, 'before_cursor_execute', reject_schema)
    try:
        with TestClient(app):
            capability = app.state.startup_capabilities['security_event_ingest_compatibility']
            assert capability['status'] == 'degraded', 'failed_security_schema_reported_ready'
    finally:
        event.remove(engine, 'before_cursor_execute', reject_schema)
        engine.dispose()
