from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_internal_mtls_blocks_without_client_headers(monkeypatch):
    monkeypatch.setenv("INTERNAL_MTLS_REQUIRED", "1")
    app = create_app()
    client = TestClient(app)
    r = client.post("/api/v1/orchestrator/events/", json={"event": "x"})
    assert r.status_code == 401
    assert (r.json() or {}).get("detail") in ("mtls_required", "mtls_client_cert_missing")

