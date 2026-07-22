import asyncio

import pytest

from src.app.routers.chat_stream import _run_with_heartbeats


@pytest.mark.asyncio
async def test_slow_chat_emits_heartbeats_without_starting_a_second_producer():
    calls = 0

    async def producer():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.035)
        return {"assistant_message": "done"}

    events = []
    async for event in _run_with_heartbeats(producer(), interval_s=0.01):
        events.append(event)

    assert calls == 1
    assert any(kind == "heartbeat" for kind, _ in events)
    assert events[-1] == ("result", {"assistant_message": "done"})


@pytest.mark.asyncio
async def test_fast_chat_returns_without_an_unnecessary_heartbeat():
    async def producer():
        return {"assistant_message": "done"}

    events = []
    async for event in _run_with_heartbeats(producer(), interval_s=0.05):
        events.append(event)

    assert events == [("result", {"assistant_message": "done"})]
