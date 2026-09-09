from contextlib import contextmanager
from types import SimpleNamespace

from src.app.routers import decisions
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
import pytest


def test_successful_empty_temporal_query_does_not_retry_other_sources(monkeypatch):
    calls = []
    class DB:
        def execute(self, statement, params):
            calls.append(str(statement))
            rows = [] if len(calls) == 1 else [{"id": "outside-time-window"}]
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))
    db = DB()
    @contextmanager
    def session():
        yield db
    monkeypatch.setattr(decisions, "_ff_get_flags", lambda: {})
    monkeypatch.setattr(decisions, "_decision_reads_enabled", lambda flags: True)
    monkeypatch.setattr(decisions, "db_session", session)
    monkeypatch.setenv("READ_REPLICA_ENABLED", "0")
    result = decisions.query_decisions(system_from="2099-01-01", db=db, role="owner")
    assert result == {"results": []}
    assert len(calls) == 1


def test_temporal_database_failure_never_switches_to_unfiltered_source(monkeypatch):
    class DB:
        def execute(self, statement, params):
            raise OperationalError("query", {}, Exception("unavailable"))
    @contextmanager
    def forbidden_session():
        pytest.fail("Temporal reads must not switch databases")
        yield
    monkeypatch.setattr(decisions, "_ff_get_flags", lambda: {})
    monkeypatch.setattr(decisions, "_decision_reads_enabled", lambda flags: True)
    monkeypatch.setattr(decisions, "db_session", forbidden_session)
    monkeypatch.setenv("READ_REPLICA_ENABLED", "0")
    with pytest.raises(HTTPException) as error:
        decisions.query_decisions(system_from="2026-01-01", db=DB(), role="owner")
    assert error.value.status_code == 503
    assert error.value.detail == "decision_history_unavailable"
