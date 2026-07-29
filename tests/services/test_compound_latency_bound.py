from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from src.app.services.recommend_bounded_narration import (
    bounded_knowledge_answer,
)


def test_bounded_knowledge_answer_skips_with_narration_mode(monkeypatch):
    called = {"value": False}

    def _slow(*args, **kwargs):
        called["value"] = True
        return "late"

    payload = {"narration_mode": "skip", "timing_breakdown": {}}
    with ThreadPoolExecutor(max_workers=1) as executor:
        out = bounded_knowledge_answer(
            payload,
            query="why those",
            plan=object(),
            results=[],
            model="test",
            trace_id="trace",
            timing_prefix="compound",
            build_answer=_slow,
            executor=executor,
        )
    assert out is None
    assert called["value"] is False
    assert payload["timing_breakdown"]["compound_skipped"] is True


def test_bounded_knowledge_answer_times_out_with_shared_budget(monkeypatch):
    def _slow(*args, **kwargs):
        time.sleep(0.25)
        return "late"

    monkeypatch.setenv("RECOMMEND_NARRATION_TIMEOUT_SEC", "0.05")
    payload = {"narration_mode": "blocking", "timing_breakdown": {}}
    started = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        out = bounded_knowledge_answer(
            payload,
            query="why those",
            plan=object(),
            results=[],
            model="test",
            trace_id="trace",
            timing_prefix="compound",
            build_answer=_slow,
            executor=executor,
        )
        elapsed = time.perf_counter() - started
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    assert out is None and elapsed < 0.20
    assert payload["timing_breakdown"]["compound_timed_out"] is True
