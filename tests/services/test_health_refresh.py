import time

from src.app.observability import health


def test_cached_snapshot_is_non_probing_and_reports_age(monkeypatch):
    health._CACHE.update({
        "ts": int(time.time()),
        "payload": {"timestamp": 123, "overall": "healthy", "dependencies": {"db": {"status": "healthy"}}},
    })
    monkeypatch.setattr(health, "_check_ollama", lambda: (_ for _ in ()).throw(
        AssertionError("cached snapshot must not probe Ollama")
    ))

    snapshot = health.dependency_health_cached_snapshot()

    assert snapshot["dependencies"]["db"]["status"] == "healthy"
    assert snapshot["stale"] is False


def test_background_refresh_is_single_flight(monkeypatch):
    calls = []

    def refresh(*, force=False):
        calls.append(force)
        time.sleep(0.03)
        return {"dependencies": {}}

    monkeypatch.setattr(health, "dependency_health_snapshot", refresh)
    health._REFRESH_IN_FLIGHT = False

    assert health.schedule_dependency_health_refresh() is True
    assert health.schedule_dependency_health_refresh() is False
    deadline = time.time() + 1
    while health._REFRESH_IN_FLIGHT and time.time() < deadline:
        time.sleep(0.01)

    assert calls == [True]
