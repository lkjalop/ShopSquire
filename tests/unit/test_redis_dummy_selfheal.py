"""get_redis DummyRedis self-heal — a server that boots while Redis is down must RECOVER its
session memory when Redis comes back, without a restart (observed live: DummyRedis was cached
forever; Redis restored, memory still gone). Also: the health check must not report the dummy
fallback as healthy."""
from __future__ import annotations

import pytest

import src.app.deps as deps


@pytest.fixture()
def clean_redis_globals(monkeypatch):
    monkeypatch.setattr(deps, "_lazy_redis", None)
    monkeypatch.setattr(deps, "_redis_warned", True)  # silence the one-shot warning in tests
    monkeypatch.setattr(deps, "_dummy_next_retry", 0.0)
    monkeypatch.setenv("APP_ENV", "local")
    yield


class _FakeReal:
    def ping(self):
        return True


def test_dummy_fallback_then_selfheal(clean_redis_globals, monkeypatch):
    monkeypatch.setattr(deps, "_create_redis_client", lambda: None)
    first = deps.get_redis()
    assert isinstance(first, deps.DummyRedis)
    # Redis comes back; retry window elapsed (next_retry forced to 0) -> real client swaps in.
    real = _FakeReal()
    monkeypatch.setattr(deps, "_create_redis_client", lambda: real)
    monkeypatch.setattr(deps, "_dummy_next_retry", 0.0)
    assert deps.get_redis() is real


def test_dummy_retry_is_rate_limited(clean_redis_globals, monkeypatch):
    monkeypatch.setattr(deps, "_create_redis_client", lambda: None)
    assert isinstance(deps.get_redis(), deps.DummyRedis)
    # Within the retry window the factory must NOT be re-invoked (no per-request reconnect storm).
    calls = []
    monkeypatch.setattr(deps, "_create_redis_client", lambda: calls.append(1) or _FakeReal())
    monkeypatch.setattr(deps, "_dummy_next_retry", float("inf"))
    assert isinstance(deps.get_redis(), deps.DummyRedis)
    assert calls == []


def test_health_check_reports_dummy_as_unhealthy(clean_redis_globals, monkeypatch):
    monkeypatch.setattr(deps, "_create_redis_client", lambda: None)
    monkeypatch.setattr(deps, "_dummy_next_retry", float("inf"))
    import src.app.observability.health as health
    monkeypatch.setattr(health, "get_redis", deps.get_redis)
    out = health._check_redis()
    assert out["status"] == "unhealthy"
    assert "dummy_fallback" in str(out.get("error") or "")
