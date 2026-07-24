"""Tier 1b — async narration job store + poll endpoint.

async mode returns the deterministic answer instantly + a job_id; the LLM prose is computed in a
worker and fetched via GET /narration/{job_id}. Unit tests use a fake redis + synchronous executor
so they're deterministic (no real LLM/redis); the integration test checks the wiring.
"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from src.app.main import app
from src.app.services.recommend_narration_jobs import (
    get_narration,
    put_narration,
    submit_narration,
)
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def setex(self, k, ttl, v):
        self.store[k] = v

    def get(self, k):
        return self.store.get(k)


class _SyncExecutor:
    def submit(self, fn, *a, **k):
        fn(*a, **k)  # run inline -> job is done by the time submit returns


def test_submit_runs_and_persists_done():
    r = _FakeRedis()
    jid = submit_narration(_SyncExecutor(), r, lambda *a, **k: ("the prose", None), "q", [], {})
    assert get_narration(r, jid) == {
        "status": "done",
        "assistant_message": "the prose",
        "storage_backend": "redis",
    }


def test_job_error_persists_error_status():
    r = _FakeRedis()

    def boom(*a, **k):
        raise RuntimeError("x")

    jid = submit_narration(_SyncExecutor(), r, boom)
    assert get_narration(r, jid)["status"] == "error"


def test_unknown_and_none_redis_safe():
    assert get_narration(_FakeRedis(), "nope") is None
    assert get_narration(None, "x") is None
    put_narration(None, "x", status="done", message="y")  # must not raise


def test_poll_endpoint_unknown_job_returns_pending():
    r = client.get("/api/v1/recommend/narration/does-not-exist")
    assert r.status_code == 200
    assert r.json()["status"] == "pending"


def test_async_mode_returns_job_id_and_poll_works():
    os.environ["RECOMMEND_NARRATION_MODE"] = "async"
    try:
        body = client.get("/api/v1/recommend/suggest", params={"uid": "u-async", "query": "gaming laptop under 1800"}).json()
        assert body.get("timing_breakdown", {}).get("narration_pending") is True
        job_id = body.get("llm_summary_job_id")
        assert isinstance(job_id, str) and job_id  # enqueued
        # poll endpoint responds with a known status (done/pending/error depending on redis+LLM)
        poll = client.get(f"/api/v1/recommend/narration/{job_id}")
        assert poll.status_code == 200 and "status" in poll.json()
    finally:
        os.environ.pop("RECOMMEND_NARRATION_MODE", None)
