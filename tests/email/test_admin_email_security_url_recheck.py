from fastapi.testclient import TestClient

from src.app.main import create_app


def test_admin_url_recheck_endpoints_process_deferred_jobs():
    app = create_app()
    client = TestClient(app)

    payload = {
        "from_addr": "billing@vendor-safe.example",
        "subject": "Invoice update",
        "body": "Please review: https://example-login-reset.security-check.invalid/auth",
        "message_id": "msg-url-recheck-admin-1",
    }
    ev = client.post("/api/v1/email_security/evaluate", json=payload, headers={"x-api-key": "local-developer-key"})
    assert ev.status_code == 200

    dash_before = client.get(
        "/api/v1/admin/email_security/url-recheck/dashboard?hours=24&limit=10",
        headers={"x-api-key": "local-owner-key"},
    )
    assert dash_before.status_code == 200
    before_body = dash_before.json()
    assert "totals" in before_body

    run = client.post(
        "/api/v1/admin/email_security/url-recheck/run-cycle",
        json={"max_jobs": 20, "now_epoch": 9999999999},
        headers={"x-api-key": "local-owner-key"},
    )
    assert run.status_code == 200
    run_body = run.json()
    assert str(run_body.get("status")) == "ok"
    assert int(run_body.get("processed") or 0) >= 1

    rep = client.post(
        "/api/v1/admin/email_security/url-recheck/replay-failed",
        json={"limit": 20, "dry_run": True},
        headers={"x-api-key": "local-owner-key"},
    )
    assert rep.status_code == 200
    rep_body = rep.json()
    assert rep_body.get("dry_run") is True
    assert "items" in rep_body
