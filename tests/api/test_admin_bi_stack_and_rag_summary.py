from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session
from tests.utils import default_headers


def test_admin_bi_db_stack_status_and_rag_summary():
    app = create_app()
    client = TestClient(app, headers=default_headers())

    s = client.get("/api/v1/admin/bi/db-stack/status")
    assert s.status_code == 200
    body = s.json()
    assert "postgres_source_of_truth" in body
    assert "redis_configured" in body

    with db_session() as db:
        db.execute(
            text(
                "INSERT OR REPLACE INTO decision_trace_events "
                "(id, trace_id, event_type, source_type, source_id, payload, created_at) "
                "VALUES (:id, :trace_id, :event_type, :source_type, :source_id, :payload, CURRENT_TIMESTAMP)"
            ),
            {
                "id": "rag-s-1",
                "trace_id": "rag-s-trace",
                "event_type": "context_injected",
                "source_type": "agent",
                "source_id": "RAG_Context_Injector_Agent",
                "payload": "{\"context_ids\":[\"faq:1\",\"faq:2\"],\"budget_chars\":1000,\"used_chars\":600}",
            },
        )
        db.commit()
    r = client.get("/api/v1/admin/bi/agentic-rag/summary?days=7")
    assert r.status_code == 200
    out = r.json()
    assert out.get("status") == "ok"
    assert int(out.get("contexts_injected") or 0) >= 2
