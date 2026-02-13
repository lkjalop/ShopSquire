import os

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_threat_intel_upsert_and_enrichment_block():
    os.environ["OWNER_API_KEY"] = "local-owner-key"
    os.environ["DEVELOPER_API_KEY"] = "local-developer-key"
    app = create_app()
    client = TestClient(app)

    up = client.post(
        "/api/v1/admin/email_security/threat-intel",
        headers={"x-api-key": "local-owner-key"},
        json={
            "tenant_id": "ti-tenant",
            "indicator_type": "domain",
            "indicator_value": "evil-payments.example",
            "verdict": "deny",
            "confidence": 0.98,
            "source": "analyst",
        },
    )
    assert up.status_code == 200
    ls = client.get("/api/v1/admin/email_security/threat-intel?tenant_id=ti-tenant", headers={"x-api-key": "local-owner-key"})
    assert ls.status_code == 200
    items = ls.json().get("items") or []
    assert any(i.get("indicator_value") == "evil-payments.example" for i in items)

    ev = client.post(
        "/api/v1/email_security/evaluate",
        headers={"x-api-key": "local-developer-key"},
        json={
            "tenant_id": "ti-tenant",
            "message_id": "ti-msg-1",
            "from_addr": "acct@supplier.example",
            "reply_to": "acct@supplier.example",
            "subject": "Payment reminder",
            "body": "Please pay via https://evil-payments.example/pay?id=1",
            "attachments": [],
        },
    )
    assert ev.status_code == 200
    out = ev.json()
    enrichment = out.get("enrichment") or {}
    assert int(enrichment.get("malicious_hits") or 0) >= 1
    assert out.get("route") in ("security_review", "human_review", "auto_resolve")

