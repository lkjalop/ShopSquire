"""Tier 1 — RECOMMEND_NARRATION_MODE: decouple LLM narration from the response.

Baseline showed LLM narration (summary_ms) is 85-91% of route latency. `skip` returns the
deterministic grounded answer with NO blocking LLM call (summary_ms == 0); `blocking` (default)
preserves the current contract. Verifies behaviour, not wall-clock (the dev LLM varies).
"""
from __future__ import annotations

import os

import pytest

from fastapi.testclient import TestClient

from src.app.main import app
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())


@pytest.fixture(autouse=True)
def _isolated_narration_quota(monkeypatch):
    """Narration mode contracts must not depend on a developer Redis usage counter."""
    monkeypatch.setenv("TOKEN_BUDGET_ENABLED", "0")


def _suggest(query="gaming laptop under 1800", uid="u-narr"):
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": query})
    assert r.status_code == 200
    return r.json()


def test_default_blocking_preserves_contract():
    # No env override -> default mode; assistant_message present, contract spine intact.
    body = _suggest(uid="u-narr-blocking")
    assert "assistant_message" in body and "results" in body
    assert body.get("timing_breakdown", {}).get("narration_mode") in (None, "blocking")


def test_skip_mode_no_llm_wait_deterministic_message():
    os.environ["RECOMMEND_NARRATION_MODE"] = "skip"
    try:
        body = _suggest(uid="u-narr-skip")
        tb = body.get("timing_breakdown", {})
        assert tb.get("narration_mode") == "skip"
        assert tb.get("summary_ms") == 0  # no blocking LLM call
        # still answers: deterministic grounded message is present (fallback path)
        assert isinstance(body.get("assistant_message"), str) and body["assistant_message"].strip()
    finally:
        os.environ.pop("RECOMMEND_NARRATION_MODE", None)


def test_async_mode_flags_pending_and_skips_llm():
    os.environ["RECOMMEND_NARRATION_MODE"] = "async"
    try:
        body = _suggest(uid="u-narr-async")
        tb = body.get("timing_breakdown", {})
        assert tb.get("narration_mode") == "async"
        assert tb.get("summary_ms") == 0 and tb.get("narration_pending") is True
        assert isinstance(body.get("assistant_message"), str) and body["assistant_message"].strip()
    finally:
        os.environ.pop("RECOMMEND_NARRATION_MODE", None)
