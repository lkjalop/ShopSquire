from fastapi.testclient import TestClient

from src.app.main import create_app


def test_connector_console_page_renders():
    client = TestClient(create_app())
    response = client.get(
        "/api/v1/admin/email_security/connectors/console",
        headers={"x-api-key": "local-owner-key"},
    )
    assert response.status_code == 200, response.text
    html = response.text
    assert "Email Security Connector Registry" in html
    assert "Connector Registry" in html
    assert "Delivery History" in html
    assert "/api/v1/admin/email_security/connectors/registry" in html


def test_connector_registry_json_renders_targets():
    client = TestClient(create_app())
    response = client.get(
        "/api/v1/admin/email_security/connectors/registry?hours=24",
        headers={"x-api-key": "local-owner-key"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body.get("targets"), list)
    assert isinstance(body.get("delivery_history"), list)
    assert any((row or {}).get("target") == "splunk_hec" for row in (body.get("targets") or []))


def test_privacy_console_page_renders():
    client = TestClient(create_app())
    response = client.get(
        "/api/v1/admin/email_security/privacy/console",
        headers={"x-api-key": "local-owner-key"},
    )
    assert response.status_code == 200, response.text
    html = response.text
    assert "Privacy Exposure Review" in html
    assert "Confirmed QR-linked PII/SSN findings only" in html
    assert "/api/v1/admin/email_security/privacy/review?limit=100" in html
    assert "Owner Scope" in html
    assert "Review workflow" in html


def test_privacy_review_json_renders_summary_shape():
    client = TestClient(create_app())
    response = client.get(
        "/api/v1/admin/email_security/privacy/review?limit=20",
        headers={"x-api-key": "local-owner-key"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body.get("items"), list)
    assert isinstance(body.get("summary"), dict)
    assert "human_verification_required" in (body.get("summary") or {})
