import time

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_demo_runbook_execute_and_walkthrough():
    app = create_app()
    client = TestClient(app)

    w = client.get("/api/v1/admin/email_security/demo/runbook", headers={"x-api-key": "local-owner-key"})
    assert w.status_code == 200
    wb = w.json()
    assert isinstance(wb.get("walkthrough"), list)
    assert wb.get("dashboards")

    r = client.post(
        "/api/v1/admin/email_security/demo/runbook/execute",
        json={"tenant_id": "t-runbook", "scenarios": ["bec", "prompt_injection", "canary", "supplier_bank_change"]},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200
    body = r.json()
    rows = body.get("results") or []
    assert len(rows) >= 4
    assert all(bool(x.get("decision_id")) for x in rows)
    assert all(bool(x.get("trace_id")) for x in rows)


def test_bulk_feedback_label_and_summary():
    app = create_app()
    client = TestClient(app)

    payload = {
        "tenant_id": "t-feedback",
        "message_id": f"msg-feedback-{int(time.time())}",
        "from_addr": "supplier@example.com",
        "reply_to": "accounts-payable@example.com",
        "subject": "Urgent wire transfer needed",
        "body": "Please process payment immediately.",
        "attachments": [],
        "dmarc_fail": True,
    }
    ev = client.post("/api/v1/email_security/evaluate", json=payload, headers={"x-api-key": "local-developer-key"})
    assert ev.status_code == 200

    inc = client.get(
        "/api/v1/admin/email_security/incidents",
        params={"tenant_id": "t-feedback", "limit": 10},
        headers={"x-api-key": "local-owner-key"},
    )
    assert inc.status_code == 200
    incidents = inc.json().get("incidents") or []
    assert incidents
    incident_id = incidents[0]["id"]

    b = client.post(
        "/api/v1/admin/email_security/feedback/bulk_label",
        json={
            "incident_ids": [incident_id],
            "outcome_type": "analyst_review",
            "outcome_value": "false_positive",
            "actor_id": "tester",
            "actor_role": "developer",
            "note": "benign supplier",
        },
        headers={"x-api-key": "local-owner-key"},
    )
    assert b.status_code == 200
    bb = b.json()
    assert bb.get("labeled", 0) >= 1

    s = client.get(
        "/api/v1/admin/email_security/feedback/summary",
        params={"tenant_id": "t-feedback", "hours": 24 * 30},
        headers={"x-api-key": "local-owner-key"},
    )
    assert s.status_code == 200
    sb = s.json()
    assert "false_positive_rate" in sb
    assert "totals" in sb


def test_connector_reliability_and_dlq_routes(monkeypatch):
    monkeypatch.setenv("SECURITY_HANDOFF_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("SECURITY_HANDOFF_BACKOFF_BASE_SECONDS", "0.01")
    monkeypatch.setenv("SECURITY_HANDOFF_BACKOFF_MAX_SECONDS", "0.02")
    monkeypatch.setenv("SPLUNK_HEC_URL", "http://127.0.0.1:1/services/collector")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "test-token")

    app = create_app()
    client = TestClient(app)

    r = client.post(
        "/api/v1/email_security/simulate",
        params={"scenario": "prompt_injection"},
        headers={"x-api-key": "local-owner-key"},
    )
    assert r.status_code == 200

    rel = client.get("/api/v1/admin/email_security/connectors/reliability?hours=24", headers={"x-api-key": "local-owner-key"})
    assert rel.status_code == 200
    rb = rel.json()
    assert "totals" in rb
    assert "by_target" in rb

    dlq = client.get("/api/v1/admin/email_security/connectors/dlq?limit=20", headers={"x-api-key": "local-owner-key"})
    assert dlq.status_code == 200
    db = dlq.json()
    assert "items" in db
    if db.get("items"):
        item_id = db["items"][0]["id"]
        rq = client.post(f"/api/v1/admin/email_security/connectors/dlq/{item_id}/requeue", headers={"x-api-key": "local-owner-key"})
        assert rq.status_code == 200


def test_ops_readiness_dashboard_metrics():
    app = create_app()
    client = TestClient(app)

    payload = {
        "tenant_id": "t-ops",
        "message_id": f"msg-ops-{int(time.time())}",
        "from_addr": "supplier@example.com",
        "reply_to": "accounts-payable@example.com",
        "subject": "Please update payment details",
        "body": "Urgent wire transfer to new account.",
        "attachments": [],
        "dmarc_fail": True,
    }
    r = client.post("/api/v1/email_security/evaluate", json=payload, headers={"x-api-key": "local-developer-key"})
    assert r.status_code == 200

    o = client.get(
        "/api/v1/admin/email_security/ops/readiness",
        params={"tenant_id": "t-ops", "hours": 24},
        headers={"x-api-key": "local-owner-key"},
    )
    assert o.status_code == 200
    body = o.json()
    assert "metrics" in body
    assert "alerts" in body
    assert "escalation_rate" in body["metrics"]
