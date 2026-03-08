from fastapi.testclient import TestClient

from src.app.main import create_app


def test_connectors_lab_profile_endpoint():
    app = create_app()
    client = TestClient(app)

    for profile in ("wazuh", "securityonion", "thehive"):
        r = client.get(
            f"/api/v1/admin/email_security/connectors/lab-profile?profile={profile}",
            headers={"x-api-key": "local-owner-key"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("profile") == profile
        assert "required_env" in body
        assert "SIEM_WEBHOOK_URL" in (body.get("required_env") or {})
        assert isinstance(body.get("validation_steps"), list)
        assert isinstance(body.get("analyst_push_fields"), list)


def test_connectors_lab_profile_rejects_unknown():
    app = create_app()
    client = TestClient(app)
    r = client.get(
        "/api/v1/admin/email_security/connectors/lab-profile?profile=unknown",
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 400
