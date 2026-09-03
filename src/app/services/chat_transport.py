"""Transport reliability primitives independent from recommendation orchestration."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable


# Strong references are required by asyncio while an HTTP request returns an
# in-progress receipt.  Redis remains the cross-process lock/result transport;
# this registry only keeps the owning process's producer alive until it writes
# that result.
_OPERATION_TASKS: dict[str, asyncio.Task[Any]] = {}
_OPERATION_STARTED: dict[str, float] = {}


def retained_operation_progress(key: str) -> dict[str, Any]:
    """Return safe timing/stage metadata for an in-process retained task."""
    task = _OPERATION_TASKS.get(key)
    started = _OPERATION_STARTED.get(key)
    chain: list[str] = []
    current = task.get_coro() if task is not None else None
    for _ in range(12):
        if current is None:
            break
        code = getattr(current, "cr_code", None) or getattr(current, "gi_code", None)
        if code is not None:
            name = str(getattr(code, "co_name", "") or "")
            if name and name not in chain:
                chain.append(name)
        current = (
            getattr(current, "cr_await", None)
            or getattr(current, "gi_yieldfrom", None)
            or getattr(current, "ag_await", None)
        )
    return {
        "status": "running" if task is not None and not task.done() else "not_running",
        "elapsed_ms": round((time.monotonic() - started) * 1000) if started else None,
        "stage": chain[-1] if chain else None,
        "await_chain": chain,
    }


def retained_operation_task(
    key: str,
    producer: Callable[[], Awaitable[Any]],
) -> tuple[asyncio.Task[Any], bool]:
    """Return the one process-local producer and whether this caller created it."""
    current = _OPERATION_TASKS.get(key)
    if current is not None and not current.done():
        return current, False
    task = asyncio.create_task(producer(), name=f"chat-operation:{key[-32:]}")
    _OPERATION_TASKS[key] = task
    _OPERATION_STARTED[key] = time.monotonic()

    def release(completed: asyncio.Task[Any]) -> None:
        # Consume and identify failures which happen after the initiating HTTP
        # request has already returned an in-progress receipt.
        if not completed.cancelled():
            try:
                failure = completed.exception()
            except asyncio.CancelledError:
                failure = None
            if failure is not None:
                logging.getLogger("shopsquire.chat.transport").error(
                    "retained chat operation failed key=%s error=%s",
                    key[-48:], failure.__class__.__name__,
                )
        if _OPERATION_TASKS.get(key) is completed:
            _OPERATION_TASKS.pop(key, None)
            _OPERATION_STARTED.pop(key, None)

    task.add_done_callback(release)
    return task, True


async def idempotent_single_flight(
    redis, key: str, producer: Callable[[], Awaitable[Any]], *,
    wait_timeout_seconds: float = 2.0,
    in_progress_factory: Callable[[str], Any] | None = None,
    error_factory: Callable[[str, Exception], Any] | None = None,
    logger: logging.Logger | None = None,
) -> Any:
    """Cache one result and prevent a stream/query fallback from double-producing it."""
    log = logger or logging.getLogger("shopsquire.chat.transport")
    result_key, lock_key = key + ":result", key + ":lock"
    token = str(uuid.uuid4())
    try:
        cached = redis.get(result_key)
    except Exception:
        cached = None
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    try:
        claimed = bool(redis.set(lock_key, token, nx=True, ex=90))
    except Exception:
        claimed = True
    if not claimed:
        deadline = time.monotonic() + max(0.0, min(float(wait_timeout_seconds or 0.0), 10.0))
        while time.monotonic() < deadline:
            await asyncio.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            try:
                cached = redis.get(result_key)
            except Exception:
                cached = None
            if cached:
                try:
                    return json.loads(cached)
                except Exception:
                    break
        if in_progress_factory is not None:
            # The operation id is stable across SSE and query fallback calls. The
            # caller can retrieve the completed envelope by repeating the request
            # with this same idempotency key; no second orchestration is started.
            return in_progress_factory(key.rsplit(":", 1)[-1])
    try:
        try:
            result = await producer()
        except Exception as exc:
            if error_factory is None:
                raise
            log.exception("single-flight producer failed key=%s", key[-48:])
            result = error_factory(key.rsplit(":", 1)[-1], exc)
        try:
            redis.setex(result_key, 120, json.dumps(result, default=str))
        except Exception as exc:
            log.debug("idem result cache skipped: %s", repr(exc)[:80])
        return result
    finally:
        try:
            held = redis.get(lock_key)
            held = held.decode() if isinstance(held, bytes) else held
            if held == token:
                redis.delete(lock_key)
        except Exception as exc:
            log.debug("idem lock release skipped: %s", repr(exc)[:80])


__all__ = [
    "idempotent_single_flight", "retained_operation_task",
    "retained_operation_progress",
]
