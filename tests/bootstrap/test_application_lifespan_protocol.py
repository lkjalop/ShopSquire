import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from src.app.models.db import create_runtime_engine, get_engine
from src.app.models.database_ownership import current_database_engine, database_owner


@pytest.mark.asyncio
@pytest.mark.parametrize('primary', [RuntimeError('required startup failed'), asyncio.CancelledError()])
async def test_cleanup_preserves_the_primary_failure_and_restores_borrowed_owner(primary):
    from src.app.bootstrap.application_lifespan import application_lifespan
    serving = create_runtime_engine('sqlite://')
    borrowed = create_runtime_engine('sqlite://')
    app = FastAPI(); app.state.engine = serving
    observed = []

    @asynccontextmanager
    async def failing_lifespan(_app):
        observed.append(('startup', get_engine()))
        raise primary
        yield  # pragma: no cover - gives this controlled failure an async context protocol

    async def failing_cleanup():
        observed.append(('shutdown', get_engine()))
        raise ValueError('secondary cleanup failed')

    try:
        with database_owner(borrowed):
            with pytest.raises(type(primary)) as caught:
                async with application_lifespan(app, failing_lifespan, failing_cleanup):
                    pytest.fail('failed startup must not yield')
            assert caught.value is primary
            assert current_database_engine() is borrowed
        assert observed == [('startup', serving), ('shutdown', serving)]
        assert current_database_engine() is None
    finally:
        serving.dispose(); borrowed.dispose()


@pytest.mark.asyncio
async def test_cleanup_failure_after_success_is_visible_and_owner_is_released():
    from src.app.bootstrap.application_lifespan import application_lifespan
    engine = create_runtime_engine('sqlite://')
    app = FastAPI(); app.state.engine = engine
    cleanup_error = RuntimeError('owned cleanup failed')

    @asynccontextmanager
    async def successful_lifespan(_app):
        assert current_database_engine() is engine
        yield

    async def failing_cleanup():
        assert current_database_engine() is engine
        raise cleanup_error

    try:
        with pytest.raises(RuntimeError) as caught:
            async with application_lifespan(app, successful_lifespan, failing_cleanup):
                assert get_engine() is engine
        assert caught.value is cleanup_error
        assert current_database_engine() is None
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_missing_application_engine_cannot_borrow_an_outer_database():
    from src.app.bootstrap.application_lifespan import application_lifespan
    borrowed = create_runtime_engine('sqlite://')
    app = FastAPI()
    called = []

    @asynccontextmanager
    async def lifespan(_app):
        called.append('startup')
        yield

    async def cleanup():
        called.append('cleanup')

    try:
        with database_owner(borrowed):
            with pytest.raises(TypeError, match='explicit SQLAlchemy database owner'):
                async with application_lifespan(app, lifespan, cleanup):
                    pytest.fail('an application without an owner must not start')
            assert current_database_engine() is borrowed
        assert called == []
    finally:
        borrowed.dispose()
