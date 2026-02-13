import os

from fastapi.testclient import TestClient


def test_email_security_evaluate_endpoint_returns_verdict():
    os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    os.environ.setdefault("DATABASE_URL", "sqlite:///test.sqlite")
    os.environ.setdefault("DISABLE_TRACING", "1")
    os.environ.setdefault("RATE_LIMIT_PER_IP_PER_MIN", "0")

    from src.app.main import create_app

    client = TestClient(create_app())
    r = client.post(
        "/api/v1/email_security/evaluate",
        headers={"x-api-key": "local-developer-key"},
        json={
            "tenant_id": "t1",
            "message_id": "<abc@xyz>",
            "from_addr": "CEO <ceo@microsoft.com>",
            "reply_to": "finance@micros0ft.com",
            "subject": "Urgent wire transfer",
            "body": "Please pay invoice at https://micros0ft-payments.com immediately.",
            "attachments": [{"name": "invoice.html"}],
            "dmarc_fail": False,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("severity") in ("warning", "error")
    assert "tags" in body and isinstance(body["tags"], list)
    assert body.get("playbook") is None or isinstance(body.get("playbook"), dict)

