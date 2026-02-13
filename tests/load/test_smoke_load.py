import os
import time
from fastapi.testclient import TestClient
from src.app.main import create_app


def _make_client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    monkeypatch.setenv("SKIP_OBSERVER_ENDPOINTS", "/api/v1/recommend,/api/v1/admin")
    app = create_app()
    client = TestClient(app)
    headers = {
        "x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key"),
        "x-skip-observer": "1",
    }
    return client, headers


def test_smoke_recommend_suggest_load(monkeypatch):
    client, headers = _make_client(monkeypatch)
    start = time.time()
    for i in range(50):
        r = client.get("/api/v1/recommend/suggest", params={"uid": "test-user", "query": "laptop"}, headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert "results" in data
    duration = time.time() - start
    # Basic SLO sanity: 50 requests in under ~30 seconds locally (relaxed for CI/dev environments)
    max_sec = float(os.getenv("SMOKE_RECOMMEND_MAX_SEC", "75"))
    assert duration < max_sec


def test_smoke_admin_overview_load(monkeypatch):
    client, headers = _make_client(monkeypatch)
    # ROLE_MERCHANT is default in tests via auth dependency; ensure endpoint responds quickly
    start = time.time()
    for i in range(30):
        r = client.get("/api/v1/admin/overview", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert "uptime_seconds" in data
    assert time.time() - start < 8
