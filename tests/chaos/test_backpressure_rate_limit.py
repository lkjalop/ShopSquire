import time
from fastapi.testclient import TestClient
from src.app.main import create_app


def test_rate_limit_hits_429_under_burst(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    monkeypatch.setenv("RATE_LIMIT_PER_IP_PER_MIN", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "2")
    app = create_app()
    client = TestClient(app)
    # First three requests should pass; subsequent within window should be 429
    statuses = []
    for _ in range(5):
        r = client.get("/api/v1/admin/overview")
        statuses.append(r.status_code)
    assert statuses.count(429) >= 1
    # After window reset, requests should succeed again
    time.sleep(2.1)
    r2 = client.get("/api/v1/admin/overview")
    assert r2.status_code in (200, 503, 401)  # allow unauthorized or busy
