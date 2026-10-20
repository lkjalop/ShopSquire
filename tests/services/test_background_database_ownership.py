"""Nested and concurrent work must keep explicit owners separate from requests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from src.app.models import db as database
from src.app.models.database_ownership import current_database_engine, database_owner


@pytest.fixture
def databases(tmp_path):
    engines = [create_engine('sqlite:///' + str(tmp_path / (str(i) + '.sqlite3')))
               for i in range(2)]
    for i, engine in enumerate(engines):
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE owner_probe (value INTEGER)'))
            connection.execute(text('INSERT INTO owner_probe VALUES (:value)'), {'value': i})
    yield engines
    for engine in engines:
        engine.dispose()


def read_owner():
    with database.db_session() as db:
        return db.execute(text('SELECT value FROM owner_probe')).scalar_one()


def test_nested_owner_restores_after_failure_and_overrides_inherited_request(databases, monkeypatch):
    first, second = databases
    monkeypatch.setattr(database, 'engine', second)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=second)))
    request_token = database.CURRENT_REQUEST.set(request)
    try:
        assert current_database_engine() is None
        with database_owner(first):
            assert database.get_engine() is first
            assert read_owner() == 0
            with pytest.raises(RuntimeError, match='owned failure'):
                with database_owner(second):
                    assert read_owner() == 1
                    raise RuntimeError('owned failure')
            assert database.get_engine() is first
            assert read_owner() == 0
            dependency = database.get_db_for_request()
            try:
                assert next(dependency).execute(text('SELECT value FROM owner_probe')).scalar_one() == 0
            finally:
                dependency.close()
        assert current_database_engine() is None
        assert read_owner() == 1
    finally:
        database.CURRENT_REQUEST.reset(request_token)


def test_concurrent_workers_do_not_replace_one_another_or_the_global_owner(databases, monkeypatch):
    monkeypatch.setattr(database, 'engine', databases[1])
    barrier = Barrier(2)

    def worker(index):
        with database_owner(databases[index]):
            barrier.wait(timeout=3)
            assert database.get_engine() is databases[index]
            return read_owner()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(worker, [0, 1])) == [0, 1]
    assert current_database_engine() is None
    assert database.get_engine() is databases[1]


def test_invalid_owner_cannot_silently_fall_back_to_global_database():
    with pytest.raises(TypeError, match='explicit SQLAlchemy database owner'):
        with database_owner(None):
            pytest.fail('Invalid owner entered')
    assert current_database_engine() is None


def test_async_siblings_and_offloaded_work_keep_their_database_owners(databases):
    import asyncio

    async def worker(engine):
        with database_owner(engine):
            await asyncio.sleep(0)
            return await asyncio.to_thread(read_owner)

    async def exercise():
        return await asyncio.gather(*(worker(engine) for engine in databases))

    assert asyncio.run(exercise()) == [0, 1]
    assert current_database_engine() is None
