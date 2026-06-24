"""Tests for recommend_post_pipeline — extracted post-processing pipeline."""
from unittest.mock import MagicMock, patch

import pytest

from src.app.services.recommend_post_pipeline import (
    PostPipelineHooks,
    PostPipelineInput,
    run_post_pipeline,
)


def _make_input(**overrides):
    defaults = dict(
        payload={"results": [{"sku": "A"}], "policy_version": "v1", "next_questions": []},
        trace_id="trace-1",
        decision_id="dec-1",
        flags={"POLICY_VERSION": "v1"},
        uid="user-1",
        uid_hash="abc123",
        query="gaming laptop",
        severity="info",
        agent_chain=[],
        retrieved_context={},
        skip_recommend_observer=True,
        probe_result={},
    )
    defaults.update(overrides)
    return PostPipelineInput(**defaults)


def _make_hooks(**overrides):
    defaults = dict(
        get_policy=lambda name: {"version": "v2"},
        apply_post_policy=lambda name, p: (dict(p), []),
        redact_payload=lambda p: (dict(p), [], None),
        ensure_trace_response=lambda p, *a, **kw: p,
        dedupe_next_questions_for_render=lambda qs: qs,
        build_model_watermark=lambda **kw: "wm-123",
        build_output_fingerprint=lambda p: "fp-456",
        apply_model_theft_output_protection=lambda p, **kw: p,
        record_meter_event=MagicMock(),
        analyze_payload=lambda p: {"severity": "info", "details": {"signals": {}}},
        emit_security_event=MagicMock(),
        auto_create_incident_for_review=MagicMock(),
        apply_checkout_handoff=lambda p, ctx: p,
        recommend_context_cls=MagicMock,
        compose_compound_if_needed=lambda p, t: p,
        finalize_response_payload=lambda p: p,
        log_trace_event=MagicMock(),
        request=MagicMock(headers={}),
        tracer=MagicMock(),
    )
    defaults.update(overrides)
    # Ensure tracer.start_as_current_span is a context manager
    defaults["tracer"].start_as_current_span.return_value.__enter__ = MagicMock()
    defaults["tracer"].start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
    return PostPipelineHooks(**defaults)


class TestRunPostPipeline:
    def test_returns_redacted_payload(self):
        inp = _make_input()
        hooks = _make_hooks()
        result = run_post_pipeline(inp, hooks)
        assert isinstance(result, dict)
        assert "results" in result

    def test_policy_version_updated(self):
        inp = _make_input()
        hooks = _make_hooks(get_policy=lambda name: {"version": "v99"})
        result = run_post_pipeline(inp, hooks)
        # The payload should have the updated version
        assert result.get("policy_version") == "v99"

    def test_watermark_applied(self):
        inp = _make_input()
        hooks = _make_hooks()
        result = run_post_pipeline(inp, hooks)
        assert result.get("model_watermark") == "wm-123"
        assert result.get("model_output_fingerprint") == "fp-456"

    def test_probe_detected_sets_status(self):
        inp = _make_input(probe_result={"detected": True, "reason": "systematic", "score": 0.9})
        hooks = _make_hooks()
        result = run_post_pipeline(inp, hooks)
        assert result.get("status") == "review_required"
        assert result["security"]["systematic_probing"]["detected"] is True

    def test_agent_chain_appended(self):
        chain = []
        inp = _make_input(agent_chain=chain)
        hooks = _make_hooks()
        run_post_pipeline(inp, hooks)
        assert any(a.get("agent") == "Policy_Agent" for a in chain)

    def test_billing_meter_called(self):
        meter = MagicMock()
        inp = _make_input()
        hooks = _make_hooks(record_meter_event=meter)
        run_post_pipeline(inp, hooks)
        meter.assert_called_once()

    def test_security_event_skipped_when_observer_disabled(self):
        sec_fn = MagicMock()
        inp = _make_input(skip_recommend_observer=True)
        hooks = _make_hooks(emit_security_event=sec_fn)
        run_post_pipeline(inp, hooks)
        sec_fn.assert_not_called()

    def test_checkout_handoff_called(self):
        handoff = MagicMock(side_effect=lambda p, ctx: {**p, "checkout_action": "buy"})
        inp = _make_input()
        hooks = _make_hooks(apply_checkout_handoff=handoff)
        result = run_post_pipeline(inp, hooks)
        handoff.assert_called_once()
        assert result.get("checkout_action") == "buy"

    def test_never_raises_on_hook_error(self):
        """Pipeline should be robust against individual hook failures."""
        inp = _make_input()
        hooks = _make_hooks(
            build_model_watermark=MagicMock(side_effect=RuntimeError("boom")),
        )
        # Should not raise
        result = run_post_pipeline(inp, hooks)
        assert isinstance(result, dict)
