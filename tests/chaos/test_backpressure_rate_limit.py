import time
from fastapi.testclient import TestClient
from src.app.main import create_app


def test_rate_limit_hits_429_under_burst(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    # The app is a session-wide singleton; set rate-limit config directly on
    # app.state instead of re-creating the app for this test.  Restore
    # originals in a finally block so subsequent tests are not affected.
    app = create_app()
    original_per_min = getattr(app.state, "rate_limit_per_min", 0)
    original_window = getattr(app.state, "rate_limit_window_sec", 60)
    app.state.rate_limit_per_min = 3
    app.state.rate_limit_window_sec = 2
    try:
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
    finally:
        app.state.rate_limit_per_min = original_per_min
        app.state.rate_limit_window_sec = original_window
