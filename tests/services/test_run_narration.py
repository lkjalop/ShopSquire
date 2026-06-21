"""recommend_narration_stage.run_narration — extracted Tier-1 narration latency control (D1 step 1).

Behaviour must match the inline route logic: blocking calls the LLM (timed), skip/async make NO
blocking LLM call (deterministic fallback fills downstream), async enqueues a background job.
summarize_fn is injected so this is testable without an LLM.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.app.services.recommend_narration_stage import (
    apply_product_claim_guard,
    build_narration_preamble,
    run_narration,
)


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


# ── apply_product_claim_guard ──
def _det(*a, **k):
    return "DETERMINISTIC GROUNDED"


def test_claim_guard_replaces_ungrounded_message_and_logs():
    logs = []
    out = apply_product_claim_guard(
        "LLM says it has a 999Hz screen", query="q", results=[{"sku": "A"}], constraints={},
        brand_budget_answer="", trace_id="t", deterministic_fn=_det,
        guard_enabled_fn=lambda: True,
        verify_fn=lambda *a, **k: SimpleNamespace(grounded=False, violations=["fake_spec"]),
        log_fn=lambda **kw: logs.append(kw),
    )
    assert out == "DETERMINISTIC GROUNDED"
    assert logs and logs[0]["event_type"] == "narration_guard_rejected"


def test_claim_guard_keeps_grounded_message():
    out = apply_product_claim_guard(
        "grounded prose", query="q", results=[{"sku": "A"}], constraints={}, brand_budget_answer="",
        trace_id="t", deterministic_fn=_det, guard_enabled_fn=lambda: True,
        verify_fn=lambda *a, **k: SimpleNamespace(grounded=True, violations=[]),
    )
    assert out == "grounded prose"


def test_claim_guard_noop_when_disabled_or_empty():
    # disabled -> verify never consulted
    out = apply_product_claim_guard(
        "msg", query="q", results=[{"sku": "A"}], constraints={}, brand_budget_answer="", trace_id="t",
        deterministic_fn=_det, guard_enabled_fn=lambda: False,
        verify_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("verify must not run")),
    )
    assert out == "msg"
    # no results -> unchanged
    assert apply_product_claim_guard(
        "msg", query="q", results=[], constraints={}, brand_budget_answer="", trace_id="t",
        deterministic_fn=_det, guard_enabled_fn=lambda: True,
        verify_fn=lambda *a, **k: SimpleNamespace(grounded=False, violations=[]),
    ) == "msg"


def test_claim_guard_never_raises_on_verify_failure():
    def _boom(*a, **k):
        raise RuntimeError("guard down")
    out = apply_product_claim_guard(
        "msg", query="q", results=[{"sku": "A"}], constraints={}, brand_budget_answer="", trace_id="t",
        deterministic_fn=_det, guard_enabled_fn=lambda: True, verify_fn=_boom,
    )
    assert out == "msg"  # failure swallowed, original kept


# ── prepare_narration ──
def test_prepare_narration_groups_outputs_and_stamps_constraints():
    from src.app.services.recommend_narration_stage import prepare_narration, NarrationPrep
    c = {}
    prep = prepare_narration(
        query="gaming laptop", query_effective="gaming laptop under 1800", constraints=c,
        results=[{"sku": "A"}, {"sku": "B"}],
        filter_meta_price={"min": 0}, strict_image_brand_hint="lenovo", inferred_image_brand="lenovo",
        demote_off_category=lambda r, q: r,
        build_brand_budget_answer=lambda q, r, cc: "BBA",
    )
    assert isinstance(prep, NarrationPrep)
    assert prep.brand_budget_answer == "BBA"
    # metadata stamped onto the constraints carried through (apply_* may rebind to a new dict).
    assert prep.constraints.get("_strict_image_brand_hint") == "lenovo"
    assert prep.constraints.get("_price_filter_meta") == {"min": 0}
    assert prep.narration_inputs is not None
    assert [r["sku"] for r in prep.results] == ["A", "B"]


def test_prepare_narration_applies_demoter():
    from src.app.services.recommend_narration_stage import prepare_narration
    prep = prepare_narration(
        query="q", query_effective="q", constraints={}, results=[{"sku": "A"}, {"sku": "ACC"}],
        filter_meta_price=None, strict_image_brand_hint=None, inferred_image_brand=None,
        demote_off_category=lambda r, q: [x for x in r if x["sku"] != "ACC"],  # drop the accessory
        build_brand_budget_answer=lambda q, r, cc: "",
    )
    assert [r["sku"] for r in prep.results] == ["A"]
