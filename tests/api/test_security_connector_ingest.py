from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.app.main import create_app


def _identity(**overrides):
    values = {
        "connector_id": "connector-a",
        "tenant_id": "tenant-authoritative",
        "provider": "crowdstrike",
        "storage_targets": ("database",),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_connector_identity_owns_tenant_even_when_payload_claims_another(monkeypatch):
    import src.app.routers.security_integrations as router

    captured = {}
    monkeypatch.setattr(router, "authenticate_security_connector", lambda **_: _identity())

    def ingest(**kwargs):
        captured.update(kwargs)
        return {
            "id": "event-1",
            "canonical": {"trace_id": "trace-1"},
            "policy": {"action": "alert"},
        }

    monkeypatch.setattr(router, "ingest_security_event", ingest)
    monkeypatch.setattr(router, "log_trace_event", lambda **_: None)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/security/events/connector-ingest",
        headers={
            "X-Security-Connector-Id": "connector-a",
            "Authorization": "Bearer correct-secret",
        },
        json={
            "event_family": "network",
            "source_id": "sensor-1",
            "event": {"tenant_id": "payload-tenant", "event_type": "network"},
        },
    )

    assert response.status_code == 200, response.text
    assert captured["authoritative_tenant_id"] == "tenant-authoritative"
    assert response.json()["connector_identity"] == {
        "connector_id": "connector-a",
        "provider": "crowdstrike",
    }


def test_connector_ingest_rejects_invalid_credential(monkeypatch):
    import src.app.routers.security_integrations as router

    def reject(**_):
        raise ValueError("invalid_security_connector_credential")

    monkeypatch.setattr(router, "authenticate_security_connector", reject)
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/security/events/connector-ingest",
        headers={
            "X-Security-Connector-Id": "connector-a",
            "Authorization": "Bearer wrong",
        },
        json={"event_family": "network", "event": {"event_type": "network"}},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_security_connector_credential"


def test_connector_ingest_rejects_unapproved_storage_target(monkeypatch):
    import src.app.routers.security_integrations as router

    monkeypatch.setattr(router, "authenticate_security_connector", lambda **_: _identity())
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/security/events/connector-ingest",
        headers={
            "X-Security-Connector-Id": "connector-a",
            "Authorization": "Bearer correct-secret",
        },
        json={
            "event_family": "network",
            "storage_targets": ["external_siem"],
            "event": {"event_type": "network"},
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "security_connector_storage_target_denied"
