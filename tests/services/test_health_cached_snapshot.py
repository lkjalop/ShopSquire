from __future__ import annotations

from src.app.observability import health


def test_cached_snapshot_never_runs_live_dependency_probes(monkeypatch) -> None:
    health._CACHE["ts"] = 0
    health._CACHE["payload"] = None
    monkeypatch.setattr(
        health,
        "_check_ollama",
        lambda: (_ for _ in ()).throw(AssertionError("live probe called")),
    )

    snapshot = health.dependency_health_cached_snapshot()

    assert snapshot["overall"] == "unknown"
    assert snapshot["stale"] is True
    assert snapshot["dependencies"] == {}


def test_cached_snapshot_reports_age_and_staleness(monkeypatch) -> None:
    monkeypatch.setattr(health.time, "time", lambda: 1000.0)
    health._CACHE["ts"] = 900
    health._CACHE["payload"] = {
        "timestamp": 900,
        "overall": "healthy",
        "dependencies": {"db": {"status": "healthy"}},
    }

    snapshot = health.dependency_health_cached_snapshot()

    assert snapshot["overall"] == "healthy"
    assert snapshot["age_seconds"] == 100
    assert snapshot["stale"] is True
