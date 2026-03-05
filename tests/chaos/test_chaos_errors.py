from fastapi.testclient import TestClient
from src.app.main import create_app


def test_chaos_error_injection_returns_500(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.sqlite")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    # The app is a session-wide singleton; manipulate app.state directly
    # instead of re-creating the app with patched env vars.
    app = create_app()
    original_prob = getattr(app.state, "chaos_error_prob", 0.0)
    original_prefixes = list(getattr(app.state, "chaos_error_prefixes", []))
    app.state.chaos_error_prob = 1.0
    app.state.chaos_error_prefixes = ["/api/v1/admin"]
    try:
        client = TestClient(app)
        r = client.get("/api/v1/admin/overview")
        assert r.status_code == 500
    finally:
        app.state.chaos_error_prob = original_prob
        app.state.chaos_error_prefixes = original_prefixes
