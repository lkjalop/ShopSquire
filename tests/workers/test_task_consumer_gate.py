"""The Redis task consumer must be OFF in local/dev/test (blocking xreadgroup against an empty/
unavailable stream churns timeouts → CLOSE_WAIT socket pileup → wedged port) and auto-ON in non-dev
when REDIS_URL is set. Explicit TASK_CONSUMER_ENABLED always wins. Mirrors trace_broker's gate.
"""
from __future__ import annotations

from src.app.workers import task_runner as tr


def test_disabled_in_local_and_test(monkeypatch):
    monkeypatch.delenv("TASK_CONSUMER_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    assert tr._task_consumer_enabled() is False
    monkeypatch.setenv("APP_ENV", "test")
    assert tr._task_consumer_enabled() is False


def test_explicit_flag_wins(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("TASK_CONSUMER_ENABLED", "1")
    assert tr._task_consumer_enabled() is True
    monkeypatch.setenv("TASK_CONSUMER_ENABLED", "0")
    assert tr._task_consumer_enabled() is False


def test_non_dev_auto_enables_only_with_redis(monkeypatch):
    monkeypatch.delenv("TASK_CONSUMER_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert tr._task_consumer_enabled() is False
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    assert tr._task_consumer_enabled() is True


def test_start_consumer_is_noop_when_disabled(monkeypatch):
    # Disabled → start_consumer must NOT spawn a thread (no wedge in local demo).
    monkeypatch.delenv("TASK_CONSUMER_ENABLED", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    tr._consumer_thread = None
    tr.start_consumer()
    assert tr._consumer_thread is None
