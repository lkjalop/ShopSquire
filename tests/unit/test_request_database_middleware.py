"""Request ownership survives streaming, offload, cancellation and WebSockets."""
import asyncio

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse
from starlette.websockets import WebSocketDisconnect

from src.app.models import db as database
from src.app.models.database_ownership import current_database_engine, database_owner, request_database_owner
from src.app.models.request_database_middleware import RequestDatabaseOwnerMiddleware
from tests.services.test_background_database_ownership import databases, read_owner


def application(engine):
    app = FastAPI()
    app.state.engine = engine
    app.add_middleware(RequestDatabaseOwnerMiddleware)

    @app.get('/stream')
    async def stream():
        async def chunks():
            yield str(read_owner())
            await asyncio.sleep(0)
            yield str(await asyncio.to_thread(read_owner))
        return StreamingResponse(chunks())

    @app.websocket('/owner')
    async def owner(socket: WebSocket):
        await socket.accept()
        await socket.send_json({'owner': read_owner()})
        await socket.close()

    @app.websocket('/public')
    async def public(socket: WebSocket):
        await socket.accept()
        await socket.send_text('public')
        await socket.close()

    return app


def test_stream_generator_and_offloaded_read_keep_the_request_owner(databases, monkeypatch):
    monkeypatch.setattr(database, 'engine', databases[1])
    with TestClient(application(databases[0])) as client:
        assert client.get('/stream').text == '00'
    assert current_database_engine() is None
    assert read_owner() == 1


def test_websocket_database_reads_use_the_serving_app(databases, monkeypatch):
    monkeypatch.setattr(database, 'engine', databases[1])
    with TestClient(application(databases[0])) as client:
        with client.websocket_connect('/owner') as socket:
            assert socket.receive_json() == {'owner': 0}
    assert current_database_engine() is None


def test_websocket_without_owner_closes_before_leaking_global_data(databases, monkeypatch):
    monkeypatch.setattr(database, 'engine', databases[1])
    with TestClient(application(None)) as client:
        with client.websocket_connect('/owner') as socket:
            with pytest.raises(WebSocketDisconnect) as failure:
                socket.receive_json()
            assert failure.value.code == 1011
    assert read_owner() == 1


def test_public_websocket_needs_no_database_owner():
    with TestClient(application(None)) as client:
        with client.websocket_connect('/public') as socket:
            assert socket.receive_text() == 'public'
    assert current_database_engine() is None


def test_request_scope_restores_nested_background_owner_after_error(databases):
    with request_database_owner(databases[0]):
        assert current_database_engine() is databases[0]
        with pytest.raises(ValueError):
            with database_owner(databases[1]):
                assert current_database_engine() is databases[1]
                raise ValueError('owned failure')
        assert current_database_engine() is databases[0]
    assert current_database_engine() is None


def test_cancelled_request_restores_its_scope(databases, monkeypatch):
    monkeypatch.setattr(database, 'engine', databases[1])

    async def exercise():
        entered = asyncio.Event()

        async def worker():
            try:
                with request_database_owner(databases[0]):
                    entered.set()
                    await asyncio.Future()
            except asyncio.CancelledError:
                assert current_database_engine() is None
                assert read_owner() == 1
                raise

        task = asyncio.create_task(worker())
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert current_database_engine() is None
