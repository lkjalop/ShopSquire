"""#6 latency — blocking narration is time-bounded (GPT-5.5: Ollama narration measured at 21-32s).

A slow LLM narration must not block the whole response: past RECOMMEND_NARRATION_TIMEOUT_SEC it
falls back to the deterministic grounded message (returns None here so the route fills it) and flags
narration_timed_out. A fast narration still returns its prose. No mode flip — still "blocking".
"""
from __future__ import annotations

import concurrent.futures
import threading
import time

from src.app.services.recommend_narration_stage import run_narration


def _run(summarize_fn, timeout_env, monkeypatch):
    monkeypatch.setenv("RECOMMEND_NARRATION_TIMEOUT_SEC", timeout_env)
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    tb: dict = {}
    try:
        return run_narration(
            tb, mode="blocking", query="q", results=[{"sku": "A", "name": "X"}], constraints={},
            summ_model="m", trace_id=None, combined_preamble=None, narration_inputs=None,
            summarize_fn=summarize_fn, executor=ex,
        ), tb
    finally:
        ex.shutdown(wait=False)


def test_slow_narration_times_out_to_deterministic(monkeypatch):
    done = threading.Event()

    def slow(*a, **k):
        done.wait(2.0)  # exceeds the 0.2s budget
        return ("LLM PROSE", None)

    (msg, _job), tb = _run(slow, "0.2", monkeypatch)
    assert msg is None                       # route's deterministic fallback fills it
    assert tb.get("narration_timed_out") is True
    done.set()


def test_fast_narration_returns_prose(monkeypatch):
    def fast(*a, **k):
        return ("LLM PROSE", "job1")

    (msg, job), tb = _run(fast, "5", monkeypatch)
    assert msg == "LLM PROSE" and job == "job1"
    assert not tb.get("narration_timed_out")


def test_no_executor_falls_back_to_synchronous(monkeypatch):
    monkeypatch.setenv("RECOMMEND_NARRATION_TIMEOUT_SEC", "5")
    tb: dict = {}
    msg, job = run_narration(
        tb, mode="blocking", query="q", results=[{"sku": "A"}], constraints={},
        summ_model="m", trace_id=None, combined_preamble=None, narration_inputs=None,
        summarize_fn=lambda *a, **k: ("SYNC PROSE", None), executor=None,
    )
    assert msg == "SYNC PROSE"
