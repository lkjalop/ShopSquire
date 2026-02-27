from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_global_request_size_cap_blocks_large_json(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", "200")
    app = create_app()
    client = TestClient(app)
    huge = {"data": "x" * 1000}
    r = client.post("/api/v1/orchestrator/events/", json=huge)
    assert r.status_code == 413
    assert (r.json() or {}).get("detail") == "request_body_too_large"
