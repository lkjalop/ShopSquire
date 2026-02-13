from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


def test_decisions_policy_split_when_reads_disabled(monkeypatch):
    monkeypatch.setenv("DECISION_LOG_WRITES_ENABLED", "0")
    app = create_app()
    client = TestClient(app, headers=default_headers())

    latest = client.get("/api/v1/decisions/latest", params={"uid": "u-policy"})
    assert latest.status_code == 200
    assert latest.json().get("available") is False
    assert latest.json().get("reason") == "decision_reads_disabled"

    trace = client.get("/api/v1/decisions/trace-policy-1")
    assert trace.status_code == 200
    assert trace.json().get("available") is False
    assert trace.json().get("reason") == "decision_reads_disabled"

    query = client.get("/api/v1/decisions/query")
    assert query.status_code == 501

    explain = client.get("/api/v1/decisions/trace-policy-1/explain")
    assert explain.status_code == 501
