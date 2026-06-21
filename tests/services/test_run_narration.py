"""recommend_narration_stage.run_narration — extracted Tier-1 narration latency control (D1 step 1).

Behaviour must match the inline route logic: blocking calls the LLM (timed), skip/async make NO
blocking LLM call (deterministic fallback fills downstream), async enqueues a background job.
summarize_fn is injected so this is testable without an LLM.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.app.services.recommend_narration_stage import build_narration_preamble, run_narration


def _summarize_spy(calls):
    def _fn(query, results, constraints, summ_model, trace_id, *, context_preamble, narration_inputs):
        calls.append({"query": query, "preamble": context_preamble})
        return ("LLM prose", "job-blocking")
    return _fn


def test_blocking_calls_llm_and_times_it():
    tb = {}
    calls = []
    am, job = run_narration(
        tb, mode="blocking", query="q", results=[], constraints={}, summ_model="m", trace_id="t",
        combined_preamble="P", narration_inputs={}, summarize_fn=_summarize_spy(calls),
    )
    assert am == "LLM prose" and job == "job-blocking"
    assert len(calls) == 1 and calls[0]["preamble"] == "P"
    assert tb["narration_mode"] == "blocking" and "summary_ms" in tb


def test_skip_makes_no_llm_call():
    tb = {}
    calls = []
    am, job = run_narration(
        tb, mode="skip", query="q", results=[], constraints={}, summ_model="m", trace_id="t",
        combined_preamble=None, narration_inputs={}, summarize_fn=_summarize_spy(calls),
    )
    assert am is None and job is None
    assert calls == []  # no blocking LLM call
    assert tb["narration_mode"] == "skip" and tb["summary_ms"] == 0 and tb["narration_pending"] is False


def test_async_enqueues_and_does_not_block():
    tb = {}
    calls = []
    submitted = []

    def _submit(executor, redis, summarize_fn, *a, **k):
        submitted.append((executor, redis))
        return "job-async"

    am, job = run_narration(
        tb, mode="async", query="q", results=[{"sku": "X"}], constraints={"b": 1}, summ_model="m",
        trace_id="t", combined_preamble="P", narration_inputs={}, summarize_fn=_summarize_spy(calls),
        executor="EXEC", redis="REDIS", submit_fn=_submit,
    )
    assert am is None and job == "job-async"
    assert calls == []  # no inline LLM call
    assert submitted == [("EXEC", "REDIS")]
    assert tb["narration_mode"] == "async" and tb["narration_pending"] is True and tb["summary_ms"] == 0


def test_invalid_mode_defaults_to_blocking():
    tb = {}
    calls = []
    am, _ = run_narration(
        tb, mode="banana", query="q", results=[], constraints={}, summ_model="m", trace_id="t",
        combined_preamble=None, narration_inputs={}, summarize_fn=_summarize_spy(calls),
    )
    assert tb["narration_mode"] == "blocking" and len(calls) == 1 and am == "LLM prose"


def test_async_submit_failure_is_swallowed():
    tb = {}

    def _boom(*a, **k):
        raise RuntimeError("queue down")

    am, job = run_narration(
        tb, mode="async", query="q", results=[], constraints={}, summ_model="m", trace_id="t",
        combined_preamble=None, narration_inputs={}, summarize_fn=lambda *a, **k: ("x", "y"),
        submit_fn=_boom,
    )
    assert am is None and job is None  # enqueue failure -> no job id, no raise
    assert tb["narration_pending"] is True


# ── build_narration_preamble ──
def _preamble(**overrides):
    base = dict(
        kv={}, structured_state={}, constraints={}, prior_shortlist=[], db=None, trace_id="t",
        mem=None, uid="u", session_context_summary="recent chat", image_cv_signals_parsed={},
        llm_model="qwen3:14b", image_feature_allowlist=SimpleNamespace(verdict="full", blocked_signals=[]),
        build_context_preamble=lambda **k: "CTX",
        trace_to_context_summary=lambda *a, **k: "TRACE",
        image_security_preamble_note=lambda sig: "",
    )
    base.update(overrides)
    return build_narration_preamble(**base)


def test_preamble_combines_memory_trace_and_session():
    combined, model = _preamble()
    assert combined == "CTX\n\nTRACE\n\nrecent chat"
    assert model == "qwen3:14b"  # clean model name left as-is


def test_preamble_resolves_display_model_name():
    _, model = _preamble(llm_model="rule-based (prefer_small)")
    assert model and "rule-based" not in model  # fell back to a real model


def test_preamble_appends_qr_and_offtopic_notes_without_flavour():
    combined, _ = _preamble(
        image_security_preamble_note=lambda sig: "[image under review]",
        image_cv_signals_parsed={"image_relevance": "off_topic"},
    )
    assert "[image under review]" in combined
    assert "based on the text query only" in combined
    assert "electronics" not in combined.lower()  # vertical-blind fallback


def test_preamble_threads_image_trust_verdict_into_constraints():
    c = {}
    _preamble(constraints=c, image_feature_allowlist=SimpleNamespace(verdict="restricted", blocked_signals=["qr"]))
    assert c["_image_feature_allowlist_verdict"] == "restricted"
    assert c["_image_feature_blocked_signals"] == ["qr"]


def test_preamble_never_raises_on_helper_failure():
    def _boom(**k):
        raise RuntimeError("ctx down")
    combined, model = _preamble(build_context_preamble=_boom)
    # ctx failed but trace + session still combine; no raise.
    assert "TRACE" in (combined or "") and model
