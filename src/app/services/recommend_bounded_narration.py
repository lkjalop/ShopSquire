"""Bounded narration execution shared by recommendation compatibility paths."""
from __future__ import annotations

import concurrent.futures
import os
import time
from collections.abc import Callable
from typing import Any


def bounded_knowledge_answer(
    payload: dict[str, Any],
    *,
    query: str,
    plan: Any,
    results: list[dict],
    model: str,
    trace_id: str | None,
    timing_prefix: str,
    build_answer: Callable[..., str | None],
    executor: concurrent.futures.Executor,
) -> str | None:
    """Run a knowledge narration within the declared model budget."""
    timing = payload.setdefault("timing_breakdown", {})
    started = time.perf_counter()
    flag_mode = None
    try:
        from src.app.feature_flags import get_flags

        flag_mode = (get_flags() or {}).get("RECOMMEND_NARRATION_MODE")
    except Exception:
        flag_mode = None
    mode = str(
        payload.get("narration_mode")
        or timing.get("narration_mode")
        or os.getenv("RECOMMEND_NARRATION_MODE", "")
        or flag_mode
        or "blocking"
    ).strip().lower()
    timing[f"{timing_prefix}_mode"] = mode
    if mode != "blocking":
        timing[f"{timing_prefix}_skipped"] = True
        timing[f"{timing_prefix}_ms"] = int(
            (time.perf_counter() - started) * 1000,
        )
        return None
    try:
        from src.app.services.model_profiles import narration_timeout_s

        budget = max(0.0, narration_timeout_s(model))
    except Exception:
        budget = 8.0
    future = executor.submit(
        build_answer,
        query,
        plan,
        results,
        model,
        trace_id,
    )
    try:
        return future.result(timeout=budget)
    except concurrent.futures.TimeoutError:
        future.cancel()
        timing[f"{timing_prefix}_timed_out"] = True
        return None
    finally:
        timing[f"{timing_prefix}_ms"] = int(
            (time.perf_counter() - started) * 1000,
        )
