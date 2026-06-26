"""run_async_safe — the asyncio.run() hang fix: works whether or not a loop is already running."""
from __future__ import annotations

import asyncio

from src.app.services.async_safe import run_async_safe


def test_runs_without_a_running_loop():
    async def c():
        return 42
    assert run_async_safe(c()) == 42


def test_runs_from_inside_a_running_loop_without_crashing():
    # This is the bug: calling asyncio.run() from within a running loop raises RuntimeError.
    async def outer():
        async def inner():
            await asyncio.sleep(0)
            return 7
        return run_async_safe(inner())  # called from INSIDE a running loop
    assert asyncio.run(outer()) == 7  # no "asyncio.run() cannot be called from a running event loop"


def test_propagates_the_coroutine_result_type():
    async def c():
        return {"ok": True, "labels": ["a", "b"]}
    assert run_async_safe(c()) == {"ok": True, "labels": ["a", "b"]}
