from fastapi.testclient import TestClient
from src.app.main import create_app


def test_nqe_slots_returns_expected_structure():
    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/v1/recommend/nqe_slots", params={"uid": "test-user-1", "query": "laptop"})
    assert resp.status_code == 200
    data = resp.json()

    assert isinstance(data, dict)
    assert "slots" in data
    assert isinstance(data["slots"], list)

    slots = data["slots"]
    # Minimal contract for each slot
    for s in slots:
        assert "name" in s
        assert "confidence" in s
        assert isinstance(s["confidence"], (float, int))

    # Expect budget to be the highest-confidence missing slot for a generic 'laptop' query
    if slots:
        # Ensure list is sorted by confidence descending
        confidences = [s["confidence"] for s in slots]
        assert confidences == sorted(confidences, reverse=True)
        assert slots[0]["name"] == "budget"

    # Context should include keys useful to NQE
    assert "context" in data
    ctx = data["context"]
    assert isinstance(ctx, dict)
    assert "prefs_meta" in ctx
    assert "session_id" in ctx
