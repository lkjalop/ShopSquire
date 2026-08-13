import asyncio

import pytest
from fastapi import FastAPI

from src.app.bootstrap.runtime_lifecycle import RuntimeLifecycle


@pytest.mark.asyncio
async def test_runtime_lifecycle_tracks_and_cancels_background_warmup(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def warm(self):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(RuntimeLifecycle, "_warm_vlm", warm)
    monkeypatch.setattr("src.app.workers.task_runner.start_consumer", lambda: None)
    monkeypatch.setattr("src.app.workers.task_runner.stop_consumer", lambda: None)
    monkeypatch.setattr("src.app.workers.task_runner.shutdown_fallback_pool", lambda: None)
    async def noop_async():
        return None
    monkeypatch.setattr("src.app.services.trace_broker.stop_stream_consumer", noop_async)
    monkeypatch.setattr(
        "src.app.services.dependency_resilience.shutdown_resilience_executor", lambda wait: None,
    )
    monkeypatch.setattr(
        "src.app.services.recommend_narration_jobs.shutdown_narration_resources", lambda wait: None,
    )
    runtime = RuntimeLifecycle(vlm_warmup_enabled=lambda: True)
    app = FastAPI()
    runtime.start(app)
    await started.wait()
    await runtime.stop()
    assert cancelled.is_set()
    assert app.state.runtime_lifecycle is runtime
    assert runtime._tasks == set()
