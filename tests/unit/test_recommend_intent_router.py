"""Tests for recommend_intent_router — extracted intent routing functions."""
from unittest.mock import MagicMock, patch

import pytest

from src.app.services.recommend_intent_router import (
    IntentRoutingResult,
    resolve_intent_routing,
    resolve_ollama_intent_rollout,
    rule_intent_summary,
    stable_rollout_bucket,
    summaries_differ,
)


class TestStableRolloutBucket:
    def test_deterministic(self):
        assert stable_rollout_bucket("abc") == stable_rollout_bucket("abc")

    def test_range(self):
        for seed in ("a", "b", "xyz", "user-123", "trace-456"):
            val = stable_rollout_bucket(seed)
            assert 0 <= val < 100

    def test_empty_defaults(self):
        assert stable_rollout_bucket(None) == stable_rollout_bucket("")


class TestResolveOllamaIntentRollout:
    def test_off_stage(self):
        out = resolve_ollama_intent_rollout({}, uid="u1", trace_id="t1")
        assert out["stage"] == "off"
        assert out["invoke_ollama"] is False
        assert out["shadow_capture"] is False

    def test_full_stage(self):
        out = resolve_ollama_intent_rollout(
            {"USE_OLLAMA_INTENT": True}, uid="u1", trace_id="t1"
        )
        assert out["stage"] == "full"
        assert out["invoke_ollama"] is True
        assert out["shadow_capture"] is True

    def test_shadow_stage(self):
        out = resolve_ollama_intent_rollout(
            {"OLLAMA_INTENT_ROUTING": {"stage": "shadow", "shadow_percent": 100}},
            uid="u1", trace_id="t1",
        )
        assert out["stage"] == "shadow"
        assert out["invoke_ollama"] is False
        assert out["shadow_capture"] is True

    def test_percent_zero(self):
        out = resolve_ollama_intent_rollout(
            {"OLLAMA_INTENT_ROUTING": {"stage": "percent", "rollout_percent": 0}},
            uid="u1", trace_id="t1",
        )
        assert out["invoke_ollama"] is False
        assert out["shadow_capture"] is True


class TestRuleIntentSummary:
    def test_basic(self):
        s = rule_intent_summary("gaming laptop", {"intent": "product_search", "preferences": {"use_case": "gaming"}})
        assert "Intent=product_search" in s
        assert "use_case=gaming" in s

    def test_empty(self):
        s = rule_intent_summary("", None)
        assert "Intent=browse" in s


class TestSummariesDiffer:
    def test_same(self):
        assert summaries_differ("hello", "HELLO") is False

    def test_different(self):
        assert summaries_differ("hello", "world") is True

    def test_both_empty(self):
        assert summaries_differ(None, None) is False


class TestResolveIntentRouting:
    @patch("src.app.services.recommend_intent_router.select_ollama_model", return_value="llama3:8b")
    @patch("src.app.services.recommend_intent_router.is_complex_query", return_value=False)
    @patch("src.app.services.recommend_intent_router.complexity_explain", return_value={"score": 2})
    def test_rule_based_fast_path(self, mock_explain, mock_complex, mock_model):
        result = resolve_intent_routing(
            query_effective="gaming laptop",
            nlp={"intent": "product_search"},
            complexity_context={},
            flags={},
            uid="u1",
            trace_id="t1",
            fast_path_enabled=True,
            log_trace_event=MagicMock(),
        )
        assert isinstance(result, IntentRoutingResult)
        assert result.model_tier == "small"
        assert result.ollama_meta["provider"] == "rules"
        assert result.timing_ms is None

    @patch("src.app.services.recommend_intent_router.select_ollama_model", return_value="mixtral:8x7b")
    @patch("src.app.services.recommend_intent_router.is_complex_query", return_value=True)
    @patch("src.app.services.recommend_intent_router.complexity_explain", return_value={"score": 7, "length_trigger": True, "matched_keywords": ["vs"], "conjunction_count": 2})
    def test_complex_query_escalates(self, mock_explain, mock_complex, mock_model):
        result = resolve_intent_routing(
            query_effective="compare MacBook Pro vs Dell XPS for programming and video editing",
            nlp={"intent": "comparison"},
            complexity_context={},
            flags={},
            uid="u2",
            trace_id="t2",
            fast_path_enabled=True,
            log_trace_event=MagicMock(),
        )
        assert result.model_tier == "big"
        assert result.ollama_meta["complex"] is True
        assert result.complexity_signals.get("length_trigger") is True

    @patch("src.app.services.recommend_intent_router.select_ollama_model", side_effect=RuntimeError("LLM down"))
    @patch("src.app.services.recommend_intent_router.is_complex_query", return_value=False)
    @patch("src.app.services.recommend_intent_router.complexity_explain", return_value={"score": 1})
    def test_fallback_on_error(self, mock_explain, mock_complex, mock_model):
        result = resolve_intent_routing(
            query_effective="laptop",
            nlp={},
            complexity_context={},
            flags={},
            uid="u3",
            trace_id="t3",
            fast_path_enabled=False,
            log_trace_event=MagicMock(),
        )
        assert result.ollama_meta["provider"] == "rules"
        assert result.model_tier == "small"
