"""Bounded coroutine bridge for synchronous workers.

This blocks its caller. Async routes should await the coroutine directly or
offload the synchronous worker with asyncio.to_thread. The worker thread keeps
the caller's tenant, request and tracing ContextVars.
"""
from __future__ import annotations

import asyncio
import contextvars
import queue
import threading
from typing import Any


def run_async_safe(coro, *, timeout_seconds: float = 300.0) -> Any:
    """Run ``coro`` from sync code with a real caller-side deadline.

    A ``ThreadPoolExecutor`` context manager is unsuitable here: after ``future.result`` times out,
    ``__exit__`` calls ``shutdown(wait=True)`` and can re-hang on the very coroutine we intended to
    abandon. A daemon thread lets the caller receive ``TimeoutError`` without waiting for executor
    shutdown. Wrapped I/O still needs its own timeout; Python cannot safely kill a running thread.
    """
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError):
        timeout = 300.0
    timeout = max(0.01, min(timeout, 3600.0))
    result: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)
    context = contextvars.copy_context()

    def _runner() -> None:
        try:
            result.put(("value", asyncio.run(coro)))
        except BaseException as exc:
            result.put(("error", exc))

    thread = threading.Thread(
        target=context.run,
        args=(_runner,),
        name="shopsquire-async-safe",
        daemon=True,
    )
    thread.start()
    try:
        kind, value = result.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError(
            f"async operation exceeded {timeout:g}s caller deadline"
        ) from exc
    if kind == "error":
        raise value
    return value
