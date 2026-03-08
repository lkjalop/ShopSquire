from fastapi.testclient import TestClient

from src.app.main import create_app


def test_connectors_dashboard_and_batch_replay(monkeypatch):
    monkeypatch.setenv("SECURITY_HANDOFF_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("SECURITY_HANDOFF_BACKOFF_BASE_SECONDS", "0.01")
    monkeypatch.setenv("SECURITY_HANDOFF_BACKOFF_MAX_SECONDS", "0.02")
    monkeypatch.setenv("SPLUNK_HEC_URL", "http://127.0.0.1:1/services/collector")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "test-token")

    app = create_app()
    client = TestClient(app)

    sim = client.post(
        "/api/v1/email_security/simulate",
        params={"scenario": "prompt_injection"},
        headers={"x-api-key": "local-owner-key"},
    )
    assert sim.status_code == 200

    dash = client.get(
        "/api/v1/admin/email_security/connectors/dashboard?hours=24&dlq_limit=20",
        headers={"x-api-key": "local-owner-key"},
    )
    assert dash.status_code == 200
    body = dash.json()
    assert "summary" in body
    assert "reliability" in body
    assert "dlq" in body
    assert isinstance((body.get("dlq") or {}).get("items"), list)

    dry = client.post(
        "/api/v1/admin/email_security/connectors/dlq/replay",
        json={"limit": 20, "dry_run": True},
        headers={"x-api-key": "local-owner-key"},
    )
    assert dry.status_code == 200
    dry_body = dry.json()
    assert dry_body.get("dry_run") is True
    assert "item_ids" in dry_body

    live = client.post(
        "/api/v1/admin/email_security/connectors/dlq/replay",
        json={"limit": 20, "dry_run": False},
        headers={"x-api-key": "local-owner-key"},
    )
    assert live.status_code == 200
    live_body = live.json()
    assert live_body.get("dry_run") is False
    assert int(live_body.get("picked") or 0) >= 0
    assert int(live_body.get("replayed") or 0) >= 0
    assert "results" in live_body

    rel = client.get("/api/v1/admin/email_security/connectors/reliability?hours=24", headers={"x-api-key": "local-owner-key"})
    assert rel.status_code == 200
    rel_body = rel.json()
    totals = rel_body.get("totals") or {}
    assert int(totals.get("attempts") or 0) >= 1
