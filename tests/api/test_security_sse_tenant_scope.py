"""Real SQLite stream rows must remain within the active operator tenant."""
import asyncio
from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
from src.app.routers import admin_bi as route


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['security_event_ingest', 'security_events'])
async def test_stream_preserves_owned_rows_and_excludes_foreign_rows(monkeypatch, source):
    engine = create_engine('sqlite://', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE security_event_ingest '
            '(id INTEGER,event_time TEXT,event_type TEXT,severity TEXT,vendor TEXT,tenant_id TEXT)'))
        connection.execute(text('CREATE TABLE security_events '
            '(id INTEGER,event_time TEXT,severity TEXT,details TEXT,tenant_id TEXT)'))
        for identifier, tenant in [(1, 'foreign'), (2, 'merchant-a')]:
            values = {'id': identifier, 'tenant': tenant}
            if source == 'security_event_ingest':
                connection.execute(text("INSERT INTO security_event_ingest VALUES "
                    "(:id,'2026-10-25','owned-event','high','fixture',:tenant)"), values)
            else:
                connection.execute(text("INSERT INTO security_events VALUES "
                    "(:id,'2026-10-25','high','{}',:tenant)"), values)

    @contextmanager
    def session():
        with Session(engine) as database:
            yield database

    async def no_delay(_seconds):
        pass

    disconnected_checks = 0

    async def disconnected():
        nonlocal disconnected_checks
        disconnected_checks += 1
        return disconnected_checks > 1

    monkeypatch.setattr(route, 'db_session', session)
    # Only the polling delay is shortened; actual SQLite and to_thread execute.
    monkeypatch.setattr(route, 'asyncio', SimpleNamespace(
        get_event_loop=asyncio.get_running_loop, sleep=no_delay))
    token = set_active_tenant_id('merchant-a')
    try:
        response = await route.security_events_stream(
            SimpleNamespace(is_disconnected=disconnected), last_id=0, role='merchant')
        frames = [frame async for frame in response.body_iterator]
        rows = [json.loads(frame[len('data: '):]) for frame in frames if frame.startswith('data: ')]
        assert rows, 'An owned positive row must reach the stream'
        assert {row['tenant_id'] for row in rows} == {'merchant-a'}
        assert {row['id'] for row in rows} == {2}
        assert {row['source'] for row in rows} == {source}
    finally:
        reset_active_tenant_id(token)
        engine.dispose()


def test_stream_rejects_unauthenticated_request_before_database(monkeypatch):
    called = []
    monkeypatch.setattr(route, 'db_session', lambda: called.append(True))
    app = FastAPI()
    app.include_router(route.router)
    with TestClient(app) as client:
        response = client.get('/api/v1/admin/bi/security-events/stream',
                              headers={'x-api-key': 'invalid-operator-key'})
    assert response.status_code in {401, 403}
    assert not called


@pytest.mark.asyncio
async def test_database_failure_is_terminal_and_does_not_look_like_an_empty_feed(monkeypatch):
    def fail():
        raise RuntimeError('PRIVATE_CONNECTION_DETAILS')

    async def connected():
        return False

    monkeypatch.setattr(route, 'db_session', fail)
    response = await route.security_events_stream(
        SimpleNamespace(is_disconnected=connected), last_id=0, role='merchant')
    try:
        frame = await asyncio.wait_for(anext(response.body_iterator), timeout=2)
        assert frame.startswith('event: error\n')
        assert 'security_stream_unavailable' in frame
        assert 'PRIVATE_CONNECTION_DETAILS' not in frame
    finally:
        await response.body_iterator.aclose()
