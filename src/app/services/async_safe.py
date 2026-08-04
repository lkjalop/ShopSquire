"""run_async_safe — run a coroutine from a SYNC context without the asyncio.run() hang/crash.

asyncio.run() raises `RuntimeError: asyncio.run() cannot be called from a running event loop` when the
caller is already inside one (e.g. a sync helper invoked from an async FastAPI route, or a thread that
happens to have a running loop). This detects that case and runs the coroutine in a fresh thread that
has no loop — preserving asyncio.run() semantics (run-to-completion, return the value) without crashing.

(orchestrator.py has an identical private copy predating this module; new call sites should import this.)
"""
from __future__ import annotations

import asyncio
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

    def _runner() -> None:
        try:
            result.put(("value", asyncio.run(coro)))
        except BaseException as exc:
            result.put(("error", exc))

    thread = threading.Thread(
        target=_runner,
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
