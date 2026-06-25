from __future__ import annotations

import time

from src.app.routers import recommend


def test_bounded_knowledge_answer_skips_with_narration_mode(monkeypatch):
    called = {"value": False}

    def _slow(*args, **kwargs):
        called["value"] = True
        return "late"

    monkeypatch.setattr(recommend, "_build_knowledge_answer", _slow)
    payload = {"narration_mode": "skip", "timing_breakdown": {}}
    out = recommend._bounded_knowledge_answer(
        payload,
        query="why those",
        plan=object(),
        results=[],
        model="test",
        trace_id="trace",
        timing_prefix="compound",
    )
    assert out is None
    assert called["value"] is False
    assert payload["timing_breakdown"]["compound_skipped"] is True


def test_bounded_knowledge_answer_times_out_with_shared_budget(monkeypatch):
    def _slow(*args, **kwargs):
        time.sleep(0.25)
        return "late"

    monkeypatch.setattr(recommend, "_build_knowledge_answer", _slow)
    monkeypatch.setenv("RECOMMEND_NARRATION_TIMEOUT_SEC", "0.05")
    payload = {"narration_mode": "blocking", "timing_breakdown": {}}
    started = time.perf_counter()
    out = recommend._bounded_knowledge_answer(
        payload,
        query="why those",
        plan=object(),
        results=[],
        model="test",
        trace_id="trace",
        timing_prefix="compound",
    )
    elapsed = time.perf_counter() - started
    assert out is None and elapsed < 0.20
    assert payload["timing_breakdown"]["compound_timed_out"] is True
