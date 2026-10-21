"""Legacy getters must use the serving app, including observer bypass paths."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from src.app.models import db as database
from src.app.models.database_ownership import current_database_engine, database_owner


def engine_value(engine):
    with engine.connect() as db:
        return db.scalar(text('SELECT value FROM request_owner_probe'))


@pytest.fixture
def owned_clients(tmp_path, monkeypatch):
    import src.app.main as main
    monkeypatch.setenv('DISABLE_TRACING', '1')
    monkeypatch.setenv('OTEL_SDK_DISABLED', 'true')
    monkeypatch.setenv('INVENTORY_WORKER_ENABLED', '0')
    engines = []
    for index in range(3):
        engine = create_engine('sqlite:///' + str(tmp_path / f'owner-{index}.sqlite3'))
        with engine.begin() as db:
            db.execute(text('CREATE TABLE request_owner_probe(value INTEGER)'))
            db.execute(text('INSERT INTO request_owner_probe VALUES (:value)'), {'value': index})
        engines.append(engine)
    factory = getattr(main, '_original_create_app', main.create_app)
    apps, clients = [], []
    for engine in engines[:2]:
        app = factory()
        app.state.engine = engine

        @app.get('/__database-owner/probe')
        async def probe(request: Request, mode: str = 'direct'):
            barrier = getattr(request.app.state, 'probe_barrier', None)
            if barrier is not None:
                await asyncio.to_thread(barrier.wait, timeout=5)
            if mode == 'session':
                with database.db_session() as db:
                    value = db.scalar(text('SELECT value FROM request_owner_probe'))
            elif mode == 'thread':
                value = await asyncio.to_thread(lambda: engine_value(database.get_engine()))
            else:
                value = engine_value(database.get_engine())
            return {'value': value}

        @app.get('/__database-owner/plain')
        def plain():
            return {'public': True}

        apps.append(app)
        clients.append(TestClient(app, base_url='http://127.0.0.1', raise_server_exceptions=False))
    # The application factory aligns its module engine with DATABASE_URL.
    # Install the deliberately foreign global only after both apps exist.
    monkeypatch.setattr(database, 'engine', engines[2])
    try:
        yield apps, clients, engines
    finally:
        for client in clients:
            client.close()
        for engine in engines:
            engine.dispose()


@pytest.mark.parametrize('mode', ['direct', 'session', 'thread'])
def test_observer_bypass_does_not_change_request_database_owner(owned_clients, mode):
    _, clients, _ = owned_clients
    response = clients[0].get('/__database-owner/probe', params={'mode': mode}, headers={'x-skip-observer': '1'})
    assert response.status_code == 200, response.text
    assert response.json() == {'value': 0}


def test_direct_getter_uses_the_owned_engine_even_when_observer_runs(owned_clients):
    _, clients, _ = owned_clients
    response = clients[0].get('/__database-owner/probe')
    assert response.status_code == 200, response.text
    assert response.json() == {'value': 0}


@pytest.mark.parametrize('invalid_engine', [None, 'sqlite://must-not-create', object()], ids=['missing', 'string', 'object'])
def test_unowned_request_cannot_read_the_global_database(owned_clients, invalid_engine):
    apps, clients, _ = owned_clients
    apps[0].state.engine = invalid_engine
    response = clients[0].get('/__database-owner/probe', headers={'x-skip-observer': '1'})
    assert response.status_code == 503
    assert response.json() == {'detail': 'database_owner_unavailable'}


def test_simultaneous_apps_do_not_read_each_other_or_the_global_database(owned_clients):
    apps, clients, _ = owned_clients
    barrier = Barrier(2)
    for app in apps:
        app.state.probe_barrier = barrier

    def work(index):
        response = clients[index].get('/__database-owner/probe', headers={'x-skip-observer': '1'})
        assert response.status_code == 200, response.text
        return response.json()['value']

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(work, [0, 1])) == [0, 1]


def test_request_cannot_inherit_an_unrelated_background_owner(owned_clients):
    _, clients, engines = owned_clients
    with database_owner(engines[2]):
        response = clients[0].get('/__database-owner/probe', headers={'x-skip-observer': '1'})
        assert response.status_code == 200, response.text
        assert response.json() == {'value': 0}
        assert current_database_engine() is engines[2]
    assert current_database_engine() is None


def test_unowned_public_response_with_no_database_access_still_works(owned_clients):
    apps, clients, engines = owned_clients
    apps[0].state.engine = None
    assert clients[0].get('/__database-owner/plain', headers={'x-skip-observer': '1'}).json() == {'public': True}
    assert current_database_engine() is None
    assert database.get_engine() is engines[2]


def test_missing_app_owner_cannot_borrow_an_explicit_background_owner(owned_clients):
    apps, clients, engines = owned_clients
    apps[0].state.engine = None
    with database_owner(engines[2]):
        response = clients[0].get('/__database-owner/probe', headers={'x-skip-observer': '1'})
        assert response.status_code == 503
        assert current_database_engine() is engines[2]
    assert current_database_engine() is None
