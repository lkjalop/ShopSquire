"""Real PostgreSQL request ownership, using only owned certificate schemas."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src.app.models import db as database
from src.app.models.database_ownership import database_owner
from tests.unit.test_request_database_middleware import application
from tests.services.test_background_database_ownership import read_owner


@pytest.fixture
def native_owners(monkeypatch):
    value = os.getenv('TEST_POSTGRES_URL')
    if not value:
        pytest.skip('TEST_POSTGRES_URL is required for isolated request ownership checks')
    url = make_url(value)
    assert url.get_backend_name() == 'postgresql'
    assert url.host in {'127.0.0.1', 'localhost'}
    assert (url.database or '').startswith('shopsquire_cert_')
    admin = create_engine(url)
    schemas = ['request_owner_' + uuid4().hex for _ in range(3)]
    engines = []
    try:
        for index, schema in enumerate(schemas):
            with admin.begin() as db:
                db.execute(text(f'CREATE SCHEMA "{schema}"'))
            engine = create_engine(url, connect_args={'connect_timeout': 3,
                'options': f'-csearch_path={schema} -cstatement_timeout=10000 -clock_timeout=5000'})
            engines.append(engine)
            with engine.begin() as db:
                db.execute(text('CREATE TABLE owner_probe(value INTEGER)'))
                db.execute(text('INSERT INTO owner_probe VALUES (:value)'), {'value': index})
        monkeypatch.setattr(database, 'engine', engines[2])
        yield engines
    finally:
        for engine in engines:
            engine.dispose()
        with admin.begin() as db:
            for schema in schemas:
                db.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def client_for(engine):
    app = application(engine)

    @app.get('/probe')
    def probe():
        return {'owner': read_owner()}

    return TestClient(app)


def test_native_stream_and_offloaded_reads_use_the_request_owner(native_owners):
    with client_for(native_owners[0]) as client:
        assert client.get('/stream').text == '00'
    assert read_owner() == 2


def test_native_websocket_does_not_use_the_global_database(native_owners):
    with client_for(native_owners[0]) as client:
        with client.websocket_connect('/owner') as socket:
            assert socket.receive_json() == {'owner': 0}


def test_native_simultaneous_request_owners_remain_independent(native_owners):
    barrier = Barrier(2)

    def work(index):
        with client_for(native_owners[index]) as client:
            barrier.wait(timeout=5)
            return client.get('/stream').text

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(work, [0, 1])) == ['00', '11']
    assert read_owner() == 2


def test_native_unowned_request_is_unavailable_without_global_fallback(native_owners):
    with client_for(None) as client:
        response = client.get('/probe')
        assert response.status_code == 503
        assert response.json() == {'detail': 'database_owner_unavailable'}
    assert read_owner() == 2


def test_native_request_overrides_and_restores_inherited_background_owner(native_owners):
    with database_owner(native_owners[2]):
        with client_for(native_owners[0]) as client:
            assert client.get('/probe').json() == {'owner': 0}
        assert read_owner() == 2
