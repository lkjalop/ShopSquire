import time

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.observability import health


def test_health_uses_cached_readiness_without_live_dependency_probe(monkeypatch):
    client = TestClient(create_app())
    health._CACHE.update({
        "ts": int(time.time()),
        "payload": {
            "timestamp": int(time.time()), "overall": "healthy",
            "dependencies": {"ollama": {"status": "healthy", "latency_ms": 99}},
        },
    })
    monkeypatch.setattr(health, "_check_ollama", lambda: (_ for _ in ()).throw(
        AssertionError("/health must not synchronously probe Ollama")
    ))

    started = time.perf_counter()
    response = client.get("/health")
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert response.status_code == 200
    assert response.json()["dependencies"]["ollama"]["status"] == "healthy"
    assert response.json()["readiness_cache"]["stale"] is False
    assert elapsed_ms < 500


def test_healthz_is_liveness_only():
    client = TestClient(create_app())
    assert client.get("/healthz").json() == {"status": "ok"}


def test_health_projects_typed_startup_capabilities(monkeypatch):
    monkeypatch.setenv("TEST_FAST_HEALTH", "1")
    app = create_app()
    app.state.startup_capabilities = {
        "optional_search_warmup": {
            "status": "degraded", "required": False,
            "error_code": "startup_optional_search_warmup_failed",
        }
    }
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["startup_capabilities"]["optional_search_warmup"] == {
        "status": "degraded", "required": False,
        "error_code": "startup_optional_search_warmup_failed",
    }
