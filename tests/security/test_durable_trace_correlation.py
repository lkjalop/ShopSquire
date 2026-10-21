"""Correlation must reflect its durable database, tenant and surviving rows."""
from uuid import uuid4

import pytest
from sqlalchemy import text

from src.app.models.db import create_runtime_engine, db_session
from src.app.models.database_ownership import database_owner
from src.app.security import security_event_ingest as ingestion


@pytest.fixture
def owners(tmp_path, monkeypatch):
    engines = [create_runtime_engine('sqlite+pysqlite:///' + (tmp_path / f'owner-{n}.sqlite3').as_posix()) for n in range(2)]
    monkeypatch.setattr(ingestion, '_SECURITY_EVENT_TABLE_READY', False)
    monkeypatch.setattr(ingestion, '_ACTOR_STATE_TABLE_READY', False)
    try:
        yield engines
    finally:
        for engine in engines:
            engine.dispose()


def ingest(engine, trace, tenant, suffix, vendor='crowdstrike', severity='critical'):
    with database_owner(engine):
        result = ingestion.ingest_security_event(vendor, {
            'event_id': suffix, 'detection_id': suffix, 'log_id': suffix,
            'trace_id': trace, 'tenant_id': tenant, 'severity': severity,
            'confidence': 1.0, 'event_type': 'network',
        }, storage_targets=['database'], authoritative_tenant_id=tenant)
    assert result['storage_results']['database'] is True
    return result


def test_replacement_worker_recovers_prior_sources_and_highest_risk(owners, monkeypatch):
    trace, tenant = uuid4().hex, uuid4().hex
    first = ingest(owners[0], trace, tenant, 'first')
    assert first['policy']['risk_band'] == 'high'
    # A replacement worker starts without the previous worker's process cache.
    monkeypatch.setattr(ingestion, '_TRACE_CORRELATION_CACHE', {}, raising=False)
    second = ingest(owners[0], trace, tenant, 'second', vendor='siem', severity='low')
    assert second['correlation']['event_count'] == 2
    assert second['correlation']['sources'] == ['crowdstrike', 'siem']
    assert second['correlation']['highest_risk_band'] == 'high'
    assert second['correlation']['multi_source'] is True


def test_same_tenant_and_trace_in_another_database_cannot_inherit_sources(owners, monkeypatch):
    trace, tenant = uuid4().hex, uuid4().hex
    ingest(owners[0], trace, tenant, 'first')
    monkeypatch.setattr(ingestion, '_SECURITY_EVENT_TABLE_READY', False)
    second = ingest(owners[1], trace, tenant, 'second', vendor='siem', severity='low')
    assert second['correlation']['event_count'] == 1
    assert second['correlation']['sources'] == ['siem']
    assert second['correlation']['highest_risk_band'] == second['policy']['risk_band']
    assert second['correlation']['multi_source'] is False


def test_deleted_durable_rows_cannot_reappear_from_process_correlation(owners):
    trace, tenant = uuid4().hex, uuid4().hex
    ingest(owners[0], trace, tenant, 'first')
    with database_owner(owners[0]), db_session() as db:
        db.execute(text('DELETE FROM security_event_ingest WHERE trace_id=:trace AND tenant_id=:tenant'),
            {'trace': trace, 'tenant': tenant})
        db.commit()
    second = ingest(owners[0], trace, tenant, 'second', vendor='siem', severity='low')
    assert second['correlation']['event_count'] == 1
    assert second['correlation']['sources'] == ['siem']
    assert second['correlation']['multi_source'] is False


def test_deduplication_and_another_tenant_preserve_exact_durable_counts(owners):
    trace, tenant = uuid4().hex, uuid4().hex
    ingest(owners[0], trace, tenant, 'first')
    other = ingest(owners[0], trace, tenant + '-other', 'foreign', vendor='siem')
    assert other['correlation']['event_count'] == 1
    duplicate = ingest(owners[0], trace, tenant, 'first')
    assert duplicate['deduped'] is True
    assert duplicate['correlation']['event_count'] == 1
    assert duplicate['correlation']['sources'] == ['crowdstrike']
