from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


def test_contract_nlp_assist_in_triage(monkeypatch):
    monkeypatch.setenv("CONTRACT_NLP_ASSIST_ENABLED", "1")
    app = create_app()
    client = TestClient(app, headers=default_headers())

    r = client.post(
        "/api/v1/support/complaints/triage",
        json={
            "message": "Our agreement has auto renew and a 90 days termination notice with no liability cap.",
            "from_domain": "example.com",
        },
    )
    assert r.status_code == 200
    body = r.json()
    contract = body.get("contract_nlp")
    assert isinstance(contract, dict)
    assert "risks" in contract
    assert "clauses" in contract
