from fastapi.testclient import TestClient

from src.app.main import create_app
from tests.utils import default_headers


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

