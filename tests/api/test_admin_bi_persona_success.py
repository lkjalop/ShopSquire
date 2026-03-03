from fastapi.testclient import TestClient
from sqlalchemy import text
import json

from src.app.main import create_app
from src.app.models.db import db_session
from tests.utils import default_headers


def test_admin_bi_persona_success_summary():
    app = create_app()
    client = TestClient(app, headers=default_headers())

    with db_session() as db:
        rows = [
            {
                "id": "ps-1",
                "trace_id": "trace-persona-1",
                "event_type": "user_query",
                "source_type": "user",
                "source_id": "u1",
                "target_type": "agent",
                "target_id": "Recommendation_Agent",
                "payload": json.dumps(
                    {
                        "query": "actually change to office work laptop",
                        "constraints": {
                            "buyer_persona": "corporate",
                            "buyer_persona_confidence": 0.82,
                        },
                    }
                ),
            },
            {
                "id": "ps-2",
                "trace_id": "trace-persona-1",
                "event_type": "session_summary_checkpoint",
                "source_type": "agent",
                "source_id": "Conversation_Memory_Agent",
                "target_type": "system",
                "target_id": None,
                "payload": json.dumps({"turn": 3, "turn_type": "result_turn"}),
            },
            {
                "id": "ps-3",
                "trace_id": "trace-persona-1",
                "event_type": "image_reupload_requested",
                "source_type": "agent",
                "source_id": "Image_Security_Gate_Agent",
                "target_type": "user",
                "target_id": "u1",
                "payload": json.dumps({"reasons": ["qr_code_detected"]}),
            },
            {
                "id": "ps-4",
                "trace_id": "trace-persona-2",
                "event_type": "user_query",
                "source_type": "user",
                "source_id": "u2",
                "target_type": "agent",
                "target_id": "Recommendation_Agent",
                "payload": json.dumps(
                    {
                        "query": "student laptop for classes and notes",
                        "constraints": {
                            "buyer_persona": "student",
                            "buyer_persona_confidence": 0.9,
                        },
                    }
                ),
            },
            {
                "id": "ps-5",
                "trace_id": "trace-persona-2",
                "event_type": "session_summary_checkpoint",
                "source_type": "agent",
                "source_id": "Conversation_Memory_Agent",
                "target_type": "system",
                "target_id": None,
                "payload": json.dumps({"turn": 2, "turn_type": "result_turn"}),
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

    resp = client.get("/api/v1/admin/bi/persona-success?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert int((body.get("totals") or {}).get("traces") or 0) >= 2
    personas = {str(x.get("persona")): x for x in (body.get("personas") or [])}
    assert "corporate" in personas
    assert "student" in personas
    assert float((personas["corporate"] or {}).get("resolution_turns_avg") or 0.0) >= 3.0
    assert float((personas["corporate"] or {}).get("reformulation_rate") or 0.0) > 0.0
    assert float((personas["corporate"] or {}).get("reupload_rate") or 0.0) > 0.0
