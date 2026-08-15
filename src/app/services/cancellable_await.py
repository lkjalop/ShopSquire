"""Cooperative cancellation bridge for governed async provider operations."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")


async def await_with_polling_cancel(
    operation: Awaitable[T],
    *,
    cancellation_requested: Callable[[], bool] | None,
    poll_interval_s: float = 0.05,
) -> tuple[T | None, bool]:
    """Cancel the child socket task on explicit cancellation or parent exit."""

    task = asyncio.create_task(operation)
    try:
        while True:
            done, _pending = await asyncio.wait(
                {task}, timeout=max(0.01, min(float(poll_interval_s), 0.5)),
            )
            if done:
                return await task, False
            if cancellation_requested and cancellation_requested():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return None, True
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


__all__ = ["await_with_polling_cancel"]
