"""Audit reads must enforce authority, tenant and both temporal axes."""
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services import decision_replay as replay
from src.app.routers import decision_time_travel as route


@pytest.fixture
def history(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as db:
        db.execute(text("""CREATE TABLE decision_logs (
            id TEXT, tenant_id TEXT, agent_name TEXT, input_data TEXT,
            retrieved_context TEXT, proposed_action TEXT, policy_version TEXT,
            execution_status TEXT, valid_from TEXT, valid_to TEXT,
            system_from TEXT, system_to TEXT)"""))
        db.execute(text("""INSERT INTO decision_logs VALUES
            ('own','default','agent','{}','{}','{}','old','executed',
             '2026-01-01',NULL,'2026-02-01','2026-03-01'),
            ('own','default','agent','{}','{}','{}','corrected','executed',
             '2026-01-01',NULL,'2026-03-01',NULL),
            ('foreign','other','agent','{}','{}','{}','private','executed',
             '2026-01-01',NULL,'2026-02-01',NULL)"""))
        db.execute(text("""CREATE TABLE decision_trace_events (
            id TEXT, tenant_id TEXT, trace_id TEXT, event_type TEXT,
            source_type TEXT, source_id TEXT, target_type TEXT, target_id TEXT,
            payload TEXT, created_at TEXT)"""))
        db.execute(text("""INSERT INTO decision_trace_events VALUES
            ('own-event','default','same-id','observed','model','m','case','c','{}','2026-01-01'),
            ('foreign-event','other','same-id','observed','model','m','case','c','{}','2026-01-01')"""))
    @contextmanager
    def session():
        with Session(engine) as db:
            yield db
    monkeypatch.setattr(replay, "db_session", session)
    yield
    engine.dispose()


def test_asof_requires_authentication(monkeypatch):
    calls = []
    monkeypatch.setattr(route, "decisions_as_of", lambda **kw: calls.append(kw) or [{"id": "secret"}])
    app = FastAPI()
    app.include_router(route.router)
    response = TestClient(app).get('/api/v1/admin/decisions/asof', params={
        'decision_id': 'own', 'timestamp': '2026-02-15',
    })
    assert response.status_code in (401, 403)
    assert calls == []


@pytest.mark.parametrize('known_at,versions', [
    ('2026-01-15', []), ('2026-02-15', ['old']), ('2026-03-01', ['corrected']),
])
def test_asof_uses_independent_knowledge_time(history, known_at, versions):
    rows = replay.decisions_as_of(timestamp='2026-01-15', known_at=known_at)
    assert [r['policy_version'] for r in rows] == versions


def test_known_foreign_id_is_not_authority(history):
    assert replay.decisions_as_of(timestamp='2026-04-01', decision_id='foreign') == []
    assert replay.replay_decision('foreign')['available'] is False


def test_causal_read_is_tenant_scoped(history):
    graph = replay.build_causal_graph('same-id')
    assert [row['id'] for row in graph['nodes']] == ['own-event']


def test_asof_denies_non_operator_role(monkeypatch):
    from src.app.security import auth
    monkeypatch.setattr(auth, 'get_role_from_key', lambda _: 'buyer')
    monkeypatch.setattr(route, 'decisions_as_of', lambda **kw: pytest.fail('unauthorized query'))
    app = FastAPI()
    app.include_router(route.router)
    response = TestClient(app).get('/api/v1/admin/decisions/asof', params={
        'decision_id':'own', 'timestamp':'2026-02-15',
    })
    assert response.status_code == 403


def test_asof_timezone_parity_and_invalid_cutoff(history):
    first = replay.decisions_as_of(timestamp='2026-01-15', known_at='2026-03-01T00:00:00Z')
    second = replay.decisions_as_of(timestamp='2026-01-15', known_at='2026-02-28T19:00:00-05:00')
    assert first == second
    with pytest.raises(ValueError):
        replay.decisions_as_of(timestamp='invalid')
