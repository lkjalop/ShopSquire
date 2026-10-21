"""A ready PostgreSQL schema cannot suppress another owned schema's startup."""
from sqlalchemy import inspect
import pytest

from tests.chaos.test_request_database_owner_postgres import native_owners
from src.app.models.database_ownership import database_owner
from src.app.security import security_event_ingest as ingestion


@pytest.mark.parametrize('table', ['security_event_ingest', 'security_event_actor_state'])
def test_native_schema_readiness_follows_each_database_owner(native_owners, monkeypatch, table):
    monkeypatch.setattr(ingestion, '_SECURITY_EVENT_TABLE_READY', False)
    monkeypatch.setattr(ingestion, '_ACTOR_STATE_TABLE_READY', False)
    for engine in native_owners[:2]:
        with database_owner(engine):
            if table == 'security_event_actor_state':
                ingestion._ensure_actor_state_table()
            else:
                ingestion.ensure_security_event_ingest_table()
        assert inspect(engine).has_table(table), 'native_owner_skipped_security_schema_initialization'
