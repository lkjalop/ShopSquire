import gc
import weakref

import pytest
from sqlalchemy import event, text

from src.app.models.db import create_runtime_engine
from src.app.services import db_read_routing as routing


@pytest.fixture(autouse=True)
def isolated_replica_cache(monkeypatch):
    monkeypatch.setattr(routing, '_READ_ENGINE', None)
    monkeypatch.setattr(routing, '_READ_ENGINE_URL', None)
    monkeypatch.delenv('READ_REPLICA_URL', raising=False)


def primary_canary():
    engine = create_runtime_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE primary_canary(value INTEGER)'))
        connection.execute(text('INSERT INTO primary_canary VALUES (17)'))
    return engine


def test_enabling_a_replica_never_disposes_the_borrowed_primary(monkeypatch, tmp_path):
    primary = primary_canary()
    disposed = []
    event.listen(primary, 'engine_disposed', lambda _engine: disposed.append(True))
    monkeypatch.setattr(routing, 'get_engine', lambda: primary)
    replica = None
    try:
        routing.replica_lag_seconds()
        monkeypatch.setenv('READ_REPLICA_URL', 'sqlite:///' + (tmp_path / 'replica.sqlite3').as_posix())
        replica = routing._get_read_engine()
        assert replica is not primary
        assert disposed == [], 'replica configuration must not dispose the serving primary'
        with primary.connect() as connection:
            assert connection.scalar(text('SELECT value FROM primary_canary')) == 17
    finally:
        if replica is not None:
            replica.dispose()
        primary.dispose()


def test_removing_replica_configuration_releases_its_owned_pool(monkeypatch, tmp_path):
    primary = primary_canary()
    monkeypatch.setattr(routing, 'get_engine', lambda: primary)
    monkeypatch.setenv('READ_REPLICA_URL', 'sqlite:///' + (tmp_path / 'replica.sqlite3').as_posix())
    replica = routing._get_read_engine()
    disposed = []
    event.listen(replica, 'engine_disposed', lambda _engine: disposed.append(True))
    try:
        with replica.connect() as connection:
            assert connection.scalar(text('SELECT 1')) == 1
        monkeypatch.delenv('READ_REPLICA_URL')
        assert routing.choose_read_engine() is primary
        assert disposed == [True]
        with primary.connect() as connection:
            assert connection.scalar(text('SELECT value FROM primary_canary')) == 17
    finally:
        replica.dispose()
        primary.dispose()


def test_default_lag_probe_does_not_retain_a_released_primary_owner(monkeypatch):
    def probe_and_release():
        primary = primary_canary()
        reference = weakref.ref(primary)
        with monkeypatch.context() as patch:
            patch.setattr(routing, 'get_engine', lambda: primary)
            routing.replica_lag_seconds()
        primary.dispose()
        return reference

    reference = probe_and_release()
    gc.collect()
    assert reference() is None


def test_switching_owned_replicas_closes_only_the_replaced_pool(monkeypatch, tmp_path):
    primary = primary_canary()
    monkeypatch.setattr(routing, 'get_engine', lambda: primary)
    monkeypatch.setenv('READ_REPLICA_URL', 'sqlite:///' + (tmp_path / 'first.sqlite3').as_posix())
    first = routing._get_read_engine()
    disposed = []
    event.listen(first, 'engine_disposed', lambda _engine: disposed.append(True))
    second = None
    try:
        monkeypatch.setenv('READ_REPLICA_URL', 'sqlite:///' + (tmp_path / 'second.sqlite3').as_posix())
        second = routing._get_read_engine()
        assert second is not first and second is not primary
        assert disposed == [True]
        with primary.connect() as connection:
            assert connection.scalar(text('SELECT value FROM primary_canary')) == 17
    finally:
        if second is not None:
            second.dispose()
        first.dispose()
        primary.dispose()


def test_failed_replica_creation_falls_back_without_disposing_primary(monkeypatch):
    primary = primary_canary()
    monkeypatch.setattr(routing, 'get_engine', lambda: primary)
    routing.replica_lag_seconds()
    monkeypatch.setenv('READ_REPLICA_URL', 'postgresql://controlled-unavailable/replica')

    def unavailable(_url):
        raise RuntimeError('controlled replica factory failure')

    monkeypatch.setattr(routing, 'create_runtime_engine', unavailable)
    try:
        assert routing._get_read_engine() is primary
        with primary.connect() as connection:
            assert connection.scalar(text('SELECT value FROM primary_canary')) == 17
    finally:
        primary.dispose()
