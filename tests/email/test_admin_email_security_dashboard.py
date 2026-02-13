import json
import time
from fastapi.testclient import TestClient

from src.app.main import create_app


def test_email_incident_visible_in_admin_lists():
    app = create_app()
    client = TestClient(app)

    # Create an incident via evaluate (DMARC fail + suspicious subject/body)
    payload = {
        "tenant_id": "t-demo",
        "message_id": f"msg-{int(time.time())}",
        "from_addr": "supplier@example.com",
        "reply_to": "accounts-payable@example.com",
        "subject": "Urgent wire transfer needed",
        "body": "Please process payment immediately.",
        "attachments": [],
        "dmarc_fail": True,
    }
    r = client.post("/api/v1/email_security/evaluate", json=payload, headers={"x-api-key": "local-developer-key"})
    assert r.status_code == 200
    verdict = r.json()
    assert verdict.get("severity") in ("warning", "error")

    # Fetch incidents with filters
    lst = client.get(
        "/api/v1/admin/email_security/incidents",
        params={"tenant_id": "t-demo", "limit": 10},
        headers={"x-api-key": "local-owner-key"},
    )
    assert lst.status_code == 200
    incidents = lst.json().get("incidents") or []
    assert len(incidents) >= 1
    inc = incidents[0]
    inc_id = inc.get("id")
    assert inc_id

    # Incident details endpoint
    det = client.get(f"/api/v1/admin/email_security/incidents/{inc_id}", headers={"x-api-key": "local-owner-key"})
    assert det.status_code == 200
    body = det.json().get("incident") or {}
    assert body.get("tenant_id") == "t-demo"
    # ticket key should exist (may be null/no ticket created)
    assert "ticket" in body

    # Supplier buckets endpoint
    sup = client.get(
        "/api/v1/admin/email_security/suppliers",
        params={"tenant_id": "t-demo", "limit": 10},
        headers={"x-api-key": "local-owner-key"},
    )
    assert sup.status_code == 200
    buckets = sup.json().get("suppliers") or []
    assert isinstance(buckets, list)
