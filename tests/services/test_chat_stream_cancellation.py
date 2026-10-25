import asyncio

import pytest

from src.app.routers.chat_stream import _run_with_heartbeats


@pytest.mark.asyncio
async def test_closing_heartbeat_stream_cancels_and_joins_producer():
    cancelled = asyncio.Event()

    async def slow_producer():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    stream = _run_with_heartbeats(slow_producer(), interval_s=0.01)
    event, payload = await anext(stream)
    assert event == "heartbeat"
    assert payload["elapsed_ms"] >= 0

    await stream.aclose()
    await asyncio.wait_for(cancelled.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_cancelled_session_entry_closes_when_worker_finishes(monkeypatch):
    import threading
    from contextlib import contextmanager
    from src.app.models import db as database
    started, release, closed = threading.Event(), threading.Event(), threading.Event()
    @contextmanager
    def delayed_session():
        started.set()
        assert release.wait(5)
        try:
            yield object()
        finally:
            closed.set()
    monkeypatch.setattr(database, 'db_session', delayed_session)
    async def consume():
        async with database.async_db_session():
            pytest.fail('cancelled entry must never yield')
    task = asyncio.create_task(consume())
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    assert await asyncio.to_thread(closed.wait, 5)
