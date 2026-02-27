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


def test_internal_mtls_blocks_when_fingerprint_not_allowlisted(monkeypatch):
    monkeypatch.setenv("INTERNAL_MTLS_REQUIRED", "1")
    monkeypatch.setenv("INTERNAL_MTLS_FAIL_CLOSED", "0")
    monkeypatch.setenv("INTERNAL_MTLS_ALLOWED_FINGERPRINTS", "abc123")
    app = create_app()
    client = TestClient(app)
    r = client.post(
        "/api/v1/orchestrator/events/",
        json={"event": "x"},
        headers={
            "x-ssl-client-verify": "SUCCESS",
            "x-ssl-client-fingerprint": "deadbeef",
        },
    )
    assert r.status_code == 403
    assert (r.json() or {}).get("detail") == "mtls_client_fingerprint_not_allowed"


def test_internal_mtls_fail_closed_untrusted_proxy(monkeypatch):
    monkeypatch.setenv("INTERNAL_MTLS_REQUIRED", "1")
    monkeypatch.setenv("INTERNAL_MTLS_FAIL_CLOSED", "1")
    monkeypatch.setenv("INTERNAL_MTLS_TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    app = create_app()
    client = TestClient(app)
    r = client.post(
        "/api/v1/orchestrator/events/",
        json={"event": "x"},
        headers={
            "x-ssl-client-verify": "SUCCESS",
            "x-client-cert": "dummy-cert",
        },
    )
    assert r.status_code == 403
    assert (r.json() or {}).get("detail") == "mtls_untrusted_proxy_source"

