from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers
from src.app.routers import query as query_router


def test_query_router_agentic_rag_mode():
    app = create_app()
    client = TestClient(app, headers=default_headers())
    resp = client.post(
        "/api/v1/query",
        json={
            "query": "My screen is broken, what is return process?",
            "pipeline": "agentic_rag",
            "dynamic_injection": True,
            "trace_id": "rag-query-1",
            "context_budget_chars": 1000,
            "max_chunks": 4,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("source") == "agentic_rag"
    assert body.get("trace_id") == "rag-query-1"
    assert isinstance(body.get("context_ids"), list)


def test_query_router_scopes_cache_to_authoritative_tenant_case_and_session(monkeypatch):
    captured = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return {"trace_id": "rag-scoped", "context_ids": []}

    monkeypatch.setattr(query_router, "run_agentic_rag_pipeline", fake_pipeline)
    app = create_app()
    headers = default_headers() | {"x-tenant-id": "tenant-cache-a"}
    client = TestClient(app, headers=headers)

    response = client.post(
        "/api/v1/query",
        json={
            "query": "What is the status of this case?",
            "pipeline": "agentic_rag",
            "tenant_id": "payload-tenant-must-not-win",
            "case_id": "case-42",
            "session_epoch": "epoch-7",
        },
    )

    assert response.status_code == 200
    assert captured["tenant_id"] == "tenant-cache-a"
    assert captured["subject_id"] == "case-42"
    assert captured["session_epoch"] == "epoch-7"
