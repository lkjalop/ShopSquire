from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from src.app.routers import vision


@pytest.mark.asyncio
async def test_timed_out_queued_image_work_never_starts(monkeypatch):
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision-test")
    monkeypatch.setattr(vision, "_IMAGE_EXECUTOR", executor)
    release = Event()
    queued_started = Event()

    def occupying_work():
        release.wait(timeout=1.0)

    def queued_work():
        queued_started.set()

    first = asyncio.create_task(
        vision._run_bounded_image_work(occupying_work, timeout=0.03)
    )
    await asyncio.sleep(0.01)
    second = asyncio.create_task(
        vision._run_bounded_image_work(queued_work, timeout=0.03)
    )

    with pytest.raises(asyncio.TimeoutError):
        await first
    with pytest.raises(asyncio.TimeoutError):
        await second
    release.set()
    await asyncio.sleep(0.05)

    assert not queued_started.is_set()
    executor.shutdown(wait=True, cancel_futures=True)
