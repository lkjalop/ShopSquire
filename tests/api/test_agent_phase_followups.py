from fastapi.testclient import TestClient

from src.app.main import create_app


def _owner_headers():
    return {"x-api-key": "local-owner-key"}


def test_security_llm10_runtime_and_email_workflow_reports_smoke():
    client = TestClient(create_app())
    r1 = client.get("/api/v1/security/llm10/runtime-report", headers=_owner_headers())
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert "thresholds" in b1
    assert "risk_band" in b1

    r2 = client.get("/api/v1/security/email/workflow-report?days=30", headers=_owner_headers())
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert "totals" in b2
    assert "rates" in b2


def test_admin_bi_ml_governance_and_reviewer_consistency_smoke():
    client = TestClient(create_app())
    r1 = client.get("/api/v1/admin/bi/ml-governance/summary?days=30", headers=_owner_headers())
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert "cf_training" in b1
    assert "forecast_governance" in b1

    r2 = client.get("/api/v1/admin/bi/hitl/reviewer-consistency?days=30", headers=_owner_headers())
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert "summary" in b2
    assert "reviewers" in b2


def test_admin_playbook_drift_alerts_endpoint_smoke():
    client = TestClient(create_app())
    r = client.get("/api/v1/admin/playbooks/ops/drift-alerts?days=30", headers=_owner_headers())
    assert r.status_code == 200, r.text
    b = r.json()
    assert "alerts" in b
    assert b.get("status") in {"ok", "error"}
