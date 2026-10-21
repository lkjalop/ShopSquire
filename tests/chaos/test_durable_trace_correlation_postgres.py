"""Durable source correlation over owned native PostgreSQL schemas."""
from uuid import uuid4

from tests.chaos.test_request_database_owner_postgres import native_owners
from tests.security.test_durable_trace_correlation import ingest
from src.app.models.database_ownership import database_owner
from src.app.security import security_event_ingest as ingestion


def test_native_correlation_preserves_counts_sources_risk_and_database_scope(native_owners, monkeypatch):
    trace, tenant = uuid4().hex, uuid4().hex
    monkeypatch.setattr(ingestion, '_SECURITY_EVENT_TABLE_READY', False)
    first = ingest(native_owners[0], trace, tenant, 'first')
    assert first['policy']['risk_band'] == 'high'
    ingest(native_owners[0], trace, tenant, 'second', vendor='siem', severity='low')
    with database_owner(native_owners[0]):
        recovered = ingestion.correlate_by_trace(trace, tenant)
    assert recovered['event_count'] == 2
    assert recovered['sources'] == ['crowdstrike', 'siem']
    assert recovered['highest_risk_band'] == 'high'
    assert recovered['multi_source'] is True
    monkeypatch.setattr(ingestion, '_SECURITY_EVENT_TABLE_READY', False)
    separate = ingest(native_owners[1], trace, tenant, 'separate', vendor='siem', severity='low')
    assert separate['correlation']['event_count'] == 1
    assert separate['correlation']['sources'] == ['siem']
    assert separate['correlation']['multi_source'] is False
