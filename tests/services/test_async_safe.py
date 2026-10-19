"""run_async_safe — the asyncio.run() hang fix: works whether or not a loop is already running."""
from __future__ import annotations

import asyncio
import time

import pytest

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


def test_timeout_returns_without_waiting_for_daemon_runner_shutdown():
    async def stuck():
        await asyncio.sleep(1.0)
        return "too late"

    started = time.perf_counter()
    with pytest.raises(TimeoutError, match="caller deadline"):
        run_async_safe(stuck(), timeout_seconds=0.03)
    assert time.perf_counter() - started < 0.25


def test_orchestrator_uses_the_same_bounded_bridge():
    from src.app.services.orchestrator import _run_async_safe
    async def stuck():
        await asyncio.sleep(1)
    async def outer():
        started = time.perf_counter()
        with pytest.raises(TimeoutError, match='caller deadline'):
            _run_async_safe(stuck(), timeout_seconds=0.03)
        assert time.perf_counter() - started < 0.25
    asyncio.run(outer())


def test_coroutine_runtime_error_is_propagated_once():
    calls = []
    async def fails():
        calls.append(1)
        raise RuntimeError('operation failed')
    with pytest.raises(RuntimeError, match='operation failed'):
        run_async_safe(fails())
    assert calls == [1]


def test_bridge_preserves_the_callers_tenant_and_trace_context():
    from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id, current_tenant_id
    token = set_active_tenant_id('bridge-owned-tenant')
    try:
        async def current():
            return current_tenant_id()
        assert run_async_safe(current()) == 'bridge-owned-tenant'
    finally:
        reset_active_tenant_id(token)
