"""run_async_safe — run a coroutine from a SYNC context without the asyncio.run() hang/crash.

asyncio.run() raises `RuntimeError: asyncio.run() cannot be called from a running event loop` when the
caller is already inside one (e.g. a sync helper invoked from an async FastAPI route, or a thread that
happens to have a running loop). This detects that case and runs the coroutine in a fresh thread that
has no loop — preserving asyncio.run() semantics (run-to-completion, return the value) without crashing.

(orchestrator.py has an identical private copy predating this module; new call sites should import this.)
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any


def run_async_safe(coro) -> Any:
    """Run ``coro`` to completion and return its result, whether or not a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # no running loop in this thread — the simple path is safe
    # we ARE inside a running loop → asyncio.run() would crash; run it in a loop-free thread instead.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
