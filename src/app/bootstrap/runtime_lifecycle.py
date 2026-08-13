"""Bounded background-service lifecycle, separate from FastAPI composition."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable

from fastapi import FastAPI


class RuntimeLifecycle:
    def __init__(self, *, vlm_warmup_enabled: Callable[[], bool]):
        self._vlm_warmup_enabled = vlm_warmup_enabled
        self._tasks: set[asyncio.Task] = set()

    def start(self, app: FastAPI) -> None:
        try:
            from src.app.workers.task_runner import start_consumer
            start_consumer()
        except Exception:
            pass
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.info("VLM warm-up skipped (Ollama not ready yet): %s", exc)

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
        except Exception:
            pass
        try:
            from src.app.services.trace_broker import stop_stream_consumer
            await stop_stream_consumer()
        except Exception:
            pass
        try:
            from src.app.services.dependency_resilience import shutdown_resilience_executor
            shutdown_resilience_executor(wait=False)
        except Exception:
            pass
        try:
            from src.app.services.recommend_narration_jobs import shutdown_narration_resources
            shutdown_narration_resources(wait=False)
        except Exception:
            pass


__all__ = ["RuntimeLifecycle"]
