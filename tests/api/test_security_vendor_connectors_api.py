from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app


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
