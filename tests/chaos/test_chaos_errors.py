from fastapi.testclient import TestClient
from src.app.main import create_app


def test_chaos_error_injection_returns_500(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    monkeypatch.setenv("CHAOS_ERROR_PROB", "1.0")
    monkeypatch.setenv("CHAOS_ERROR_PREFIXES", "/api/v1/admin")
    app = create_app()
    client = TestClient(app)
    r = client.get("/api/v1/admin/overview")
    assert r.status_code == 500
