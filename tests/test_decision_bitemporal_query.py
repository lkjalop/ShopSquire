"""Isolated decision-history contract tests; never mutate application globals."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from src.app.routers import decisions


@pytest.fixture
def history(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE decision_logs (
                id TEXT PRIMARY KEY, agent_name TEXT, valid_from TEXT, valid_to TEXT,
                system_from TEXT, system_to TEXT, input_data TEXT, proposed_action TEXT,
                policy_version TEXT, approval_required BOOLEAN, execution_status TEXT,
                tenant_id TEXT NOT NULL DEFAULT 'default'
            )
        """))
        connection.execute(text("""
            INSERT INTO decision_logs (id, agent_name, valid_from, valid_to, system_from,
                system_to, input_data, proposed_action, policy_version, approval_required, execution_status) VALUES
            ('original', 'agent', '2026-01-01', NULL, '2026-02-01', '2026-03-01',
             '{}', '{}', 'v1', 0, 'executed'),
            ('corrected', 'agent', '2026-01-01', NULL, '2026-03-01', NULL,
             '{}', '{}', 'v2', 0, 'executed')
        """))
    monkeypatch.setattr(decisions, "_ff_get_flags", lambda: {})
    monkeypatch.setattr(decisions, "_decision_reads_enabled", lambda _: True)
    monkeypatch.setenv("READ_REPLICA_ENABLED", "0")
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_decision_query_includes_bitemporal_fields(history):
    rows = decisions.query_decisions(db=history, role="owner")["results"]
    assert {row["id"] for row in rows} == {"original", "corrected"}
    assert all(row["valid_from"] and row["system_from"] for row in rows)


def test_temporal_range_filter_preserves_empty_result(history):
    assert decisions.query_decisions(system_from="2099-01-01", db=history, role="owner") == {"results": []}


def test_history_cannot_read_another_tenant(history):
    history.execute(text("UPDATE decision_logs SET tenant_id='other' WHERE id='corrected'"))
    result = decisions.query_decisions(db=history, role="owner")
    assert [row["id"] for row in result["results"]] == ["original"]


def test_equivalent_timezone_cutoffs_return_identical_history(history):
    utc = decisions.query_decisions(known_at="2026-03-01T00:00:00Z", db=history, role="owner")
    offset = decisions.query_decisions(known_at="2026-02-28T19:00:00-05:00", db=history, role="owner")
    assert utc == offset


def test_invalid_temporal_cutoff_is_rejected(history):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        decisions.query_decisions(known_at="not-a-date", db=history, role="owner")
    assert error.value.status_code == 422


@pytest.mark.parametrize("known_at,expected", [
    ("2026-01-15", []),
    ("2026-02-15", ["original"]),
    ("2026-03-01", ["corrected"]),
])
def test_retroactive_correction_respects_knowledge_time(history, known_at, expected):
    result = decisions.query_decisions(valid_at="2026-01-15", known_at=known_at,
                                      db=history, role="owner")
    assert [row["id"] for row in result["results"]] == expected
