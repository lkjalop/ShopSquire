from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_security_pcap_correlate_endpoint():
    client = TestClient(create_app())
    blob = b"api.example.com aaaaaaaaaaaaaaaaaaaaaaaaaaaa.exfil.example.org"
    r = client.post(
        "/api/v1/security/pcap/analyze-and-correlate",
        headers={"x-api-key": "local-owner-key"},
        json={"pcap_b64": base64.b64encode(blob).decode("utf-8"), "trace_id": "trace-pcap-1", "tenant_id": "t1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "analysis" in body and "correlation" in body
    assert body["correlation"]["trace_id"] == "trace-pcap-1"


def test_security_vuln_scan_scope_guard(monkeypatch):
    monkeypatch.setenv("VULN_SCAN_ALLOWED_SUFFIXES", ".example.com")
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/security/vulnerability/scan",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "t1", "targets": ["api.example.com", "bad.evil.org"], "dry_run": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is False
    assert body.get("reason") == "scan_scope_denied"
    artifacts = client.get("/api/v1/admin/compliance/artifacts?limit=20", headers={"x-api-key": "local-owner-key"})
    assert artifacts.status_code == 200, artifacts.text
    rows = (artifacts.json() or {}).get("results") or []
    assert any(str(r.get("artifact_type")) == "vulnerability_scan" for r in rows)


def test_security_pentest_simulation_boundaries():
    client = TestClient(create_app())
    blocked = client.post(
        "/api/v1/security/pentest/simulate",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "t1", "scenario": "api_authz_sim", "simulation_only": False, "targets": ["api.example.com"]},
    )
    assert blocked.status_code == 400
    allowed = client.post(
        "/api/v1/security/pentest/simulate",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "t1", "scenario": "api_authz_sim", "simulation_only": True, "targets": ["api.example.com"]},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json().get("status") == "simulated"
    artifacts = client.get("/api/v1/admin/compliance/artifacts?limit=20", headers={"x-api-key": "local-owner-key"})
    assert artifacts.status_code == 200, artifacts.text
    rows = (artifacts.json() or {}).get("results") or []
    assert any(str(r.get("artifact_type")) == "pentest" for r in rows)
