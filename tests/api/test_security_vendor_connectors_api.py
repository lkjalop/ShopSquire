from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.services.decision_log import log_trace_event


class _Resp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_firewall_syslog_ingest_endpoint():
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/security/events/ingest/firewall-syslog",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "tenant-fw",
            "trace_id": "trace-fw-1",
            "lines": [
                "2026-02-26T10:10:00Z action=deny src=10.0.0.5 dst=8.8.8.8 severity=high event_id=fw-x1",
                "2026-02-26T10:10:01Z action=allow src=10.0.0.6 dst=1.1.1.1 severity=low event_id=fw-x2",
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert int(body.get("ingested") or 0) == 2


def test_process_tree_ingest_endpoint():
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/security/events/ingest/process-tree",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "tenant-proc",
            "trace_id": "trace-proc-1",
            "events": [
                {
                    "event_time": "2026-02-26T10:10:00Z",
                    "process_name": "powershell.exe",
                    "parent_process": "WINWORD.EXE",
                    "command_line": "powershell -enc AAAA",
                    "event_id": "proc-x1",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert int(body.get("ingested") or 0) == 1


def test_dns_proxy_ingest_endpoint():
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/security/events/ingest/dns-proxy",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "tenant-dns",
            "trace_id": "trace-dns-1",
            "lines": [
                "2026-02-26T10:10:00Z action=allow src=10.0.0.5 dst=203.0.113.99 domain=c2.example.com severity=high event_id=dns-x1",
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert int(body.get("ingested") or 0) == 1


def test_edr_memory_ingest_endpoint():
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/security/events/ingest/edr-memory",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "tenant-edr",
            "trace_id": "trace-edr-1",
            "events": [
                {
                    "event_time": "2026-02-26T10:10:00Z",
                    "process_name": "powershell.exe",
                    "detection_name": "ProcessTampering",
                    "memory_strings": "VirtualAlloc CreateRemoteThread reflective loader",
                    "event_id": "edrmem-x1",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert int(body.get("ingested") or 0) == 1


def test_crowdstrike_pull_endpoint_with_mock(monkeypatch):
    from src.app.security import vendor_connectors as vc

    def _fake_post(url, data=None, timeout=None):  # noqa: ANN001
        return _Resp(200, {"access_token": "tok-1"})

    def _fake_get(url, params=None, headers=None, timeout=None):  # noqa: ANN001
        if "queries/detects" in url:
            return _Resp(200, {"resources": ["det-1", "det-2"]})
        return _Resp(
            200,
            {
                "resources": [
                    {
                        "id": "det-1",
                        "detection_id": "det-1",
                        "created_timestamp": "2026-02-26T10:00:00Z",
                        "severity": "high",
                        "local_ip": "10.0.0.10",
                        "external_ip": "8.8.8.8",
                        "device_id": "dev-1",
                        "user_name": "alice",
                    },
                    {
                        "id": "det-2",
                        "detection_id": "det-2",
                        "created_timestamp": "2026-02-26T10:00:01Z",
                        "severity": "medium",
                        "local_ip": "10.0.0.11",
                        "external_ip": "1.1.1.1",
                        "device_id": "dev-2",
                        "user_name": "bob",
                    },
                ]
            },
        )

    monkeypatch.setattr(vc.requests, "post", _fake_post)
    monkeypatch.setattr(vc.requests, "get", _fake_get)
    monkeypatch.setenv("CROWDSTRIKE_CLIENT_ID", "id")
    monkeypatch.setenv("CROWDSTRIKE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("CROWDSTRIKE_API_URL", "https://example-cs.local")

    client = TestClient(create_app())
    r = client.post(
        "/api/v1/security/events/pull/crowdstrike",
        headers={"x-api-key": "local-owner-key"},
        json={"tenant_id": "tenant-cs", "trace_id": "trace-cs-1", "limit": 10, "lookback_minutes": 120},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert int(body.get("ingested") or 0) == 2


def test_runtime_status_reports_private_sandbox_and_recent_ingests(monkeypatch):
    import src.app.routers.security_integrations as security_integrations

    monkeypatch.setenv("PRIVATE_SANDBOX_URL", "https://sandbox.example.local")
    monkeypatch.setenv("PRIVATE_SANDBOX_TOKEN", "tok-1")
    monkeypatch.setattr(
        security_integrations,
        "_http_health_probe",
        lambda url: {
            "configured": True,
            "basic_connectivity": True,
            "health_endpoint": f"{str(url).rstrip('/')}/health",
            "status_code": 200,
        },
    )

    client = TestClient(create_app())
    client.post(
        "/api/v1/security/events/ingest/process-tree",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "tenant-status",
            "trace_id": "trace-status-1",
            "events": [
                {
                    "event_time": "2026-02-26T10:10:00Z",
                    "process_name": "powershell.exe",
                    "parent_process": "WINWORD.EXE",
                    "command_line": "powershell -enc AAAA",
                    "event_id": "proc-status-1",
                }
            ],
        },
    )
    client.post(
        "/api/v1/security/events/ingest/dns-proxy",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "tenant-status",
            "trace_id": "trace-status-1",
            "lines": [
                "2026-02-26T10:10:00Z action=allow src=10.0.0.5 dst=203.0.113.99 domain=c2.example.com severity=high event_id=dns-status-1",
            ],
        },
    )
    client.post(
        "/api/v1/security/events/ingest/firewall-syslog",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "tenant-status",
            "trace_id": "trace-status-1",
            "lines": [
                "2026-02-26T10:10:00Z action=deny src=10.0.0.5 dst=203.0.113.99 severity=high event_id=fw-status-1",
            ],
        },
    )
    log_trace_event(
        trace_id="trace-status-1",
        event_type="security_scan",
        source_type="security",
        source_id="runtime_swarm_lab",
        target_type="incident",
        target_id="inc-status-1",
        payload={
            "security": {
                "attack_hypothesis": "c2_beacon",
                "claim_status": "possible",
                "evidence_lane": "pending_runtime_confirmation",
                "runtime_evidence_present": ["endpoint_process_tree: runtime process lineage confirmed"],
                "runtime_evidence_required": ["sandbox_detonation: real provider confirmation required"],
                "evidence": {
                    "summary": "Runtime confirmation pending for c2 beacon.",
                    "runtime_label": "Pending real provider-backed runtime evidence.",
                },
            }
        },
    )

    r = client.get(
        "/api/v1/security/runtime/status?tenant_id=tenant-status&limit=5",
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sandbox_provider_health"]["configured"] is True
    assert body["sandbox_provider_health"]["basic_connectivity"] is True
    assert body["recent_ingests"]["process_tree"][0]["trace_id"] == "trace-status-1"
    assert body["recent_ingests"]["dns_proxy"][0]["trace_id"] == "trace-status-1"
    assert body["recent_ingests"]["firewall"][0]["trace_id"] == "trace-status-1"
    assert "edr_memory" in body["recent_ingests"]


def test_runtime_case_status_explains_pending_reasons(monkeypatch):
    monkeypatch.setenv("PRIVATE_SANDBOX_URL", "")

    client = TestClient(create_app())
    client.post(
        "/api/v1/security/events/ingest/process-tree",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "tenant-case",
            "trace_id": "trace-case-1",
            "events": [
                {
                    "event_time": "2026-02-26T10:10:00Z",
                    "process_name": "powershell.exe",
                    "parent_process": "WINWORD.EXE",
                    "command_line": "powershell -enc AAAA",
                    "event_id": "proc-case-1",
                }
            ],
        },
    )
    log_trace_event(
        trace_id="trace-case-1",
        event_type="security_scan",
        source_type="security",
        source_id="runtime_swarm_lab",
        target_type="incident",
        target_id="inc-case-1",
        payload={
            "security": {
                "attack_hypothesis": "lolbin_command_sequence",
                "claim_status": "possible",
                "evidence_lane": "pending_runtime_confirmation",
                "runtime_evidence_present": ["endpoint_process_tree: runtime process lineage confirmed"],
                "runtime_evidence_required": [
                    "sandbox_detonation: real provider confirmation required",
                    "dns_proxy_firewall_logs: runtime DNS/proxy/firewall evidence required",
                ],
                "evidence": {
                    "summary": "Runtime confirmation pending for lolbin command sequence.",
                    "runtime_label": "Pending real provider-backed runtime evidence.",
                },
            }
        },
    )

    r = client.get(
        "/api/v1/security/runtime/cases/trace-case-1",
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trace_id"] == "trace-case-1"
    assert body["confirmation_tier"] == "pending_runtime_evidence"
    assert any(item["requirement"] == "sandbox_detonation" for item in body["pending_reasons"])
    assert any(item["requirement"] == "dns_proxy_firewall_logs" for item in body["pending_reasons"])
    assert body["recent_ingests"]["process_tree"][0]["trace_id"] == "trace-case-1"
