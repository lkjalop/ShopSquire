import os
import json
import pytest
import uuid

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.security.email_security import evaluate_email_security


def test_email_security_api_evaluate_basic_info_severity():
    # Ensure local developer key works for auth
    os.environ["DEVELOPER_API_KEY"] = "local-developer-key"
    app = create_app()
    client = TestClient(app)

    payload = {
        "tenant_id": "test-tenant",
        "message_id": "msg-123",
        "from_addr": "ceo@example.com",
        "reply_to": "ceo@example.com",
        "subject": "Quarterly update",
        "body": "Normal note. Please review the draft.",
        "attachments": [],
        "dmarc_fail": False,
    }

    r = client.post("/api/v1/email_security/evaluate", headers={"x-api-key": "local-developer-key"}, json=payload)
    assert r.status_code == 200
    data = r.json()
    # Basic shape assertions
    assert isinstance(data, dict)
    assert data.get("severity") in {"info", "warning", "error"}
    # playbook selection keys may be present
    assert "evidence_snapshot" in data


def test_email_security_verdict_triggers_ticket_on_warning(monkeypatch):
    # Monkeypatch TicketingAgent to track calls
    created = {"called": False}

    class DummyTkt:
        def create_ticket(self, **kwargs):
            created["called"] = True
            # Simulate returning an object with id
            class _T:
                id = "TKT-12345"
            return _T()

    monkeypatch.setenv("TICKET_RATE_LIMIT_ENABLED", "0")
    monkeypatch.setenv("TICKET_RATE_LIMIT", json.dumps({"enabled": False, "per_min": 100}))
    monkeypatch.setenv("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    # Patch the agent used inside evaluate_email_security
    monkeypatch.setitem(evaluate_email_security.__globals__, "TicketingAgent", DummyTkt)

    email = {
        "message_id": f"msg-warn-{uuid.uuid4()}",
        "from_addr": "finance@company.com",
        "reply_to": "finance@company.com",
        "subject": "Urgent wire transfer needed",
        "body": "Please wire transfer funds ASAP to the new account.",
        "attachments": [],
        # Explicitly mark a DMARC fail to increase severity
        "dmarc_fail": True,
    }

    v = evaluate_email_security(email, tenant_id="tenant-x")
    assert v["severity"] in {"warning", "error"}
    assert created["called"] is True
