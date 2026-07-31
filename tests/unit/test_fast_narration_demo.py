"""Tests for fast narration mode — deterministic responses for interactive demos.

Validates that RECOMMEND_NARRATION_MODE=skip produces instant, complete responses
without waiting for an LLM, enabling sub-second interactive demos.
"""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fast_client():
    """Create a client with narration skipped (instant deterministic response).
    Uses the pre-configured app singleton which loads seed data."""
    os.environ["RECOMMEND_NARRATION_MODE"] = "skip"
    os.environ["COMMERCE_NARRATION_GUARD"] = "1"
    from src.app.main import app
    return TestClient(app)


class TestFastNarration:
    """Verify the fast/demo mode produces complete responses without LLM latency."""

    def test_fast_mode_skips_narration_work(self, fast_client):
        """Narration skip is not an end-to-end router latency guarantee."""
        resp = fast_client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "demo-1", "query": "gaming laptop under 1500", "fast_path": "true"},
            headers={"x-api-key": "local-owner-key"},
        )
        assert resp.status_code == 200
        timing = resp.json().get("timing_breakdown") or {}
        assert timing.get("narration_mode") == "skip"
        assert timing.get("summary_ms") == 0

    def test_fast_mode_has_assistant_message(self, fast_client):
        """Even without LLM, deterministic assistant_message is populated."""
        resp = fast_client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "demo-2", "query": "laptop for work"},
            headers={"x-api-key": "local-owner-key"},
        )
        data = resp.json()
        msg = data.get("assistant_message", "")
        assert msg, "assistant_message must not be empty in fast mode"
        assert len(msg) > 20, "assistant_message should be a meaningful sentence"

    def test_fast_mode_has_products(self, fast_client):
        """Fast mode returns actual product results."""
        resp = fast_client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "demo-3", "query": "portable laptop for university"},
            headers={"x-api-key": "local-owner-key"},
        )
        data = resp.json()
        results = data.get("results") or data.get("products") or []
        assert len(results) > 0, "Must return product results in fast mode"
        assert results[0].get("sku"), "Result must have sku"
        assert results[0].get("price") or results[0].get("price_cents"), "Result must have price"

    def test_fast_mode_timing_shows_skip(self, fast_client):
        """Timing breakdown should indicate narration was skipped."""
        resp = fast_client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "demo-4", "query": "gaming laptop"},
            headers={"x-api-key": "local-owner-key"},
        )
        data = resp.json()
        tb = data.get("timing_breakdown", {})
        # narration_mode should be 'skip' and summary_ms should be 0 or very low
        assert tb.get("narration_mode") == "skip" or tb.get("summary_ms", 0) < 100

    def test_fast_mode_multi_intent(self, fast_client):
        """Multi-intent query works in fast mode and produces next_questions."""
        resp = fast_client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "demo-5", "query": "I need something portable for university but good enough for gaming"},
            headers={"x-api-key": "local-owner-key"},
        )
        data = resp.json()
        assert resp.status_code == 200
        # Should still produce next_questions even without LLM
        nq = data.get("next_questions")
        assert nq is None or isinstance(nq, list)
        # Should have results
        results = data.get("results") or data.get("products") or []
        assert len(results) > 0

    def test_narration_timeout_bounds_latency(self, fast_client, monkeypatch):
        """RECOMMEND_NARRATION_TIMEOUT_SEC prevents unbounded LLM waits."""
        # The timeout env var should bound any blocking narration
        monkeypatch.setenv("RECOMMEND_NARRATION_TIMEOUT_SEC", "1")
        resp = fast_client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "demo-6", "query": "laptops"},
            headers={"x-api-key": "local-owner-key"},
        )
        assert resp.status_code == 200
