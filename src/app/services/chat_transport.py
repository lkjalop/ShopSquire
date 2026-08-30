"""Transport reliability primitives independent from recommendation orchestration."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable


async def idempotent_single_flight(
    redis, key: str, producer: Callable[[], Awaitable[Any]], *,
    wait_timeout_seconds: float = 2.0,
    in_progress_factory: Callable[[str], Any] | None = None,
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
        result = await producer()
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


__all__ = ["idempotent_single_flight"]
