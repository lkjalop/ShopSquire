"""Async narration job store — in-process fallback (2026-07-09, GPT-5.5's DummyRedis catch).

The async narration path used ONLY Redis; when Redis is unreachable the app drops to DummyRedis
(a no-op), so jobs vanished and the poll returned 'pending' forever — the brain silently muted
with no signal. These lock in: the in-process fallback makes async work without Redis, and the
record is fail-visible (storage_backend)."""
from __future__ import annotations

from src.app.deps import DummyRedis
from src.app.services import recommend_narration_jobs as J


def test_roundtrip_with_dummyredis_uses_memory():
    J.put_narration(DummyRedis(), "j1", status="done", message="the prose", meta={"guard": "passed"})
    rec = J.get_narration(DummyRedis(), "j1")
    assert rec and rec["assistant_message"] == "the prose"
    assert rec["storage_backend"] == "memory"   # fail-visible: never silently muted again
    assert rec["guard"] == "passed"


def test_roundtrip_with_none_redis():
    J.put_narration(None, "j2", status="done", message="m2")
    assert J.get_narration(None, "j2")["assistant_message"] == "m2"


def test_unknown_job_is_none():
    assert J.get_narration(DummyRedis(), "does-not-exist") is None


def test_full_submit_flow_resolves_without_redis():
    # the exact failure GPT-5.5 found: submit -> worker -> poll, all on DummyRedis
    from concurrent.futures import ThreadPoolExecutor
    ex = ThreadPoolExecutor(max_workers=1)
    jid = J.submit_narration(ex, DummyRedis(), lambda: ("computed prose", None))
    ex.shutdown(wait=True)  # let the worker finish
    rec = J.get_narration(DummyRedis(), jid)
    assert rec["status"] == "done" and rec["assistant_message"] == "computed prose"


def test_real_redis_client_is_preferred_and_marked():
    class _FakeRedis:  # not named DummyRedis -> treated as live
        store = {}
        def setex(self, k, ttl, v): self.store[k] = v
        def get(self, k): return self.store.get(k)
    r = _FakeRedis()
    J.put_narration(r, "j3", status="done", message="via redis")
    rec = J.get_narration(r, "j3")
    assert rec["storage_backend"] == "redis"
