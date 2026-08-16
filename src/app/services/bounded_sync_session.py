"""Transitional isolation for sync SQLAlchemy work called by async routes.

The worker owns both its Session and its private event loop. This keeps legacy
sync SQLAlchemy off the ASGI event loop while complete AsyncSession transaction
boundaries are migrated one at a time. No ORM object may cross this boundary.
"""
from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import Request
from sqlalchemy.orm import sessionmaker

from src.app.models.db import get_engine


T = TypeVar("T")
SyncSessionOperation = Callable[[object, Callable[[], bool]], Awaitable[T]]
_DB_SLOTS = threading.BoundedSemaphore(value=4)


async def run_isolated_sync_session(
    request: Request,
    operation: SyncSessionOperation[T],
    *,
    timeout_s: float = 45.0,
) -> T:
    """Run a legacy DB/network workflow without blocking the ASGI event loop.

    This is deliberately transitional. The session is created, used and closed
    on one bounded worker. A disconnect/timeout becomes cooperative cancellation
    input for the research transports; a timed-out result is never returned.
    """

    state = getattr(request.app, "state", None)
    engine = (
        getattr(state, "engine", None)
        or getattr(state, "test_engine", None)
        or get_engine()
    )
    cancellation = threading.Event()
    context = contextvars.copy_context()

    def invoke() -> T:
        if not _DB_SLOTS.acquire(timeout=0.25):
            raise RuntimeError("shopping_case_db_capacity_exhausted")
        factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
        session = factory()
        try:
            return asyncio.run(operation(session, cancellation.is_set))
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
            _DB_SLOTS.release()

    async def watch_disconnect() -> None:
        while not cancellation.is_set():
            if await request.is_disconnected():
                cancellation.set()
                return
            await asyncio.sleep(0.05)

    watcher = asyncio.create_task(watch_disconnect())
    future = asyncio.create_task(asyncio.to_thread(context.run, invoke))
    try:
        return await asyncio.wait_for(future, timeout=timeout_s)
    except (TimeoutError, asyncio.CancelledError):
        cancellation.set()
        raise
    finally:
        cancellation.set()
        watcher.cancel()


__all__ = ["run_isolated_sync_session"]
