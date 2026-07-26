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
    headers = {
        "x-api-key": "local-owner-key",
        "x-tenant-id": "tenant-test",
    }
    r1 = client.post("/api/v1/recommend/nqe_feedback", json=body, headers=headers)
    assert r1.status_code == 200, r1.text
    r2 = client.get(
        "/api/v1/recommend/admin/nqe_feedback_summary?tenant_id=tenant-test&days=30",
        headers=headers,
    )
    assert r2.status_code == 200
    items = (r2.json() or {}).get("items") or []
    assert isinstance(items, list)


def test_nqe_feedback_rejects_body_tenant_override():
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/recommend/nqe_feedback",
        headers={
            "x-api-key": "local-owner-key",
            "x-tenant-id": "tenant-a",
        },
        json={
            "trace_id": "trace-cross-tenant",
            "question_id": "ask_budget",
            "tenant_id": "tenant-b",
            "converted": False,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "cross_tenant_nqe_feedback"
