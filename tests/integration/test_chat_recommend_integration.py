import json
from fastapi.testclient import TestClient

from src.app.main import create_app


def test_chat_to_recommend_integration():
    app = create_app()
    client = TestClient(app)

    # create a lightweight chat/recommend request that goes through recommend.suggest
    headers = {"x-api-key": "local-merchant-key"}
    # Use a deterministic uid that maps to guest tier
    uid = "test_guest_123"
    resp = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": uid, "query": "laptop under $1000", "budget_max": 1000},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # Basic contract expectations
    assert "results" in data
    assert "proposal" in data
    assert data.get("policy_version") is not None
    assert "evidence_items" in data
    assert "evidence_weighting" in data
    assert "confidence_calibrated" in data
    assert "counterfactual" in data
