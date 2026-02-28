from fastapi.testclient import TestClient
from sqlalchemy import text
import json

from src.app.main import create_app
from src.app.models.db import db_session
from tests.utils import default_headers


def test_admin_bi_memory_health_summary():
    app = create_app()
    client = TestClient(app, headers=default_headers())

    with db_session() as db:
        rows = [
            {
                "id": "mh-1",
                "trace_id": "trace-mh-1",
                "event_type": "memory_health",
                "source_type": "agent",
                "source_id": "Conversation_Memory_Agent",
                "target_type": "system",
                "target_id": None,
                "payload": json.dumps(
                    {
                        "memory_confidence": 0.32,
                        "memory_miss": True,
                        "shortlist_lock_failed": True,
                        "summary_age_sec": 120,
                        "stale_slots": ["budget"],
                    }
                ),
            },
            {
                "id": "mh-2",
                "trace_id": "trace-mh-2",
                "event_type": "session_summary_checkpoint",
                "source_type": "agent",
                "source_id": "Conversation_Memory_Agent",
                "target_type": "system",
                "target_id": None,
                "payload": json.dumps({"turn": 10}),
            },
            {
                "id": "mh-3",
                "trace_id": "trace-mh-3",
                "event_type": "memory_disambiguation_prompted",
                "source_type": "agent",
                "source_id": "Conversation_Memory_Agent",
                "target_type": "user",
                "target_id": "u1",
                "payload": json.dumps({"memory_confidence": 0.2}),
            },
        ]
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO decision_trace_events
                (id, trace_id, event_type, source_type, source_id, target_type, target_id, payload, created_at)
                VALUES
                (:id, :trace_id, :event_type, :source_type, :source_id, :target_type, :target_id, :payload, CURRENT_TIMESTAMP)
                """
            ),
            rows,
        )
        db.commit()

    resp = client.get("/api/v1/admin/bi/memory-health?days=14")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("days") == 14
    totals = body.get("totals") or {}
    assert int(totals.get("events") or 0) >= 3
    assert int(totals.get("memory_miss") or 0) >= 1
    assert int(totals.get("shortlist_lock_failed") or 0) >= 1
    assert int(totals.get("disambiguation_prompts") or 0) >= 1
    assert int(totals.get("summary_checkpoints") or 0) >= 1
