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
