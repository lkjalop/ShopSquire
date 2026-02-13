from fastapi.testclient import TestClient

from src.app.main import create_app


def test_nqe_feedback_and_summary_endpoints():
    app = create_app()
    client = TestClient(app)
    body = {
        "trace_id": "trace-nqe-1",
        "question_id": "ask_budget",
        "tenant_id": "tenant-test",
        "variant": "control",
        "converted": True,
        "latency_ms": 350,
    }
    r1 = client.post("/api/v1/recommend/nqe_feedback", json=body, headers={"x-api-key": "local-owner-key"})
    assert r1.status_code == 200
    r2 = client.get("/api/v1/recommend/admin/nqe_feedback_summary?tenant_id=tenant-test&days=30", headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200
    items = (r2.json() or {}).get("items") or []
    assert isinstance(items, list)
