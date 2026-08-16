"""Bounded background-service lifecycle, separate from FastAPI composition."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable

from fastapi import FastAPI

from src.app.bootstrap.startup_readiness import record_shutdown_result, run_startup_step


class RuntimeLifecycle:
    def __init__(self, *, vlm_warmup_enabled: Callable[[], bool]):
        self._vlm_warmup_enabled = vlm_warmup_enabled
        self._tasks: set[asyncio.Task] = set()
        self._app: FastAPI | None = None

    def start(self, app: FastAPI) -> None:
        self._app = app

        def _start_consumer() -> None:
            from src.app.workers.task_runner import start_consumer
            start_consumer()
        run_startup_step(
            app, name="task_consumer", criticality="optional", operation=_start_consumer,
        )
        if self._vlm_warmup_enabled():
            task = asyncio.create_task(self._warm_vlm(), name="shopsquire-vlm-warmup")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        app.state.runtime_lifecycle = self

    async def _warm_vlm(self) -> None:
        import httpx

        log = logging.getLogger("shopsquire.startup")
        base = (os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
        model = (
            os.getenv("CV_VISION_MODEL") or os.getenv("OLLAMA_VISION_MODEL") or "qwen3-vl:8b"
        ).strip()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                await client.post(
                    f"{base}/api/generate",
                    json={"model": model, "prompt": "hi", "stream": False,
                          "options": {"num_predict": 1}},
                )
            log.info("VLM warm-up complete: model=%s url=%s", model, base)
            if self._app is not None:
                from src.app.bootstrap.startup_readiness import run_startup_step
                run_startup_step(
                    self._app, name="vlm_warmup", criticality="optional",
                    operation=lambda: None,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.info("VLM warm-up skipped (Ollama not ready yet): %s", exc)
            if self._app is not None:
                def _raise_warmup_error(error=exc) -> None:
                    raise error

                run_startup_step(
                    self._app, name="vlm_warmup", criticality="optional",
                    operation=_raise_warmup_error,
                )

    async def stop(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._tasks.clear()
        try:
            from src.app.workers.task_runner import shutdown_fallback_pool, stop_consumer
            stop_consumer()
            shutdown_fallback_pool()
            if self._app is not None:
                record_shutdown_result(self._app, name="task_consumer", criticality="optional")
        except Exception as exc:
            if self._app is not None:
                record_shutdown_result(
                    self._app, name="task_consumer", criticality="optional", error=exc,
                )
        try:
            from src.app.services.trace_broker import stop_stream_consumer
            await stop_stream_consumer()
        except Exception as exc:
            if self._app is not None:
                record_shutdown_result(
                    self._app, name="trace_stream_consumer", criticality="optional", error=exc,
                )
        try:
            from src.app.services.dependency_resilience import shutdown_resilience_executor
            shutdown_resilience_executor(wait=False)
        except Exception as exc:
            if self._app is not None:
                record_shutdown_result(
                    self._app, name="resilience_executor", criticality="optional", error=exc,
                )
        try:
            from src.app.services.recommend_narration_jobs import shutdown_narration_resources
            shutdown_narration_resources(wait=False)
        except Exception as exc:
            if self._app is not None:
                record_shutdown_result(
                    self._app, name="narration_resources", criticality="optional", error=exc,
                )


__all__ = ["RuntimeLifecycle"]
