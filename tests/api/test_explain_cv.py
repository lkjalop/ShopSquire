import os
import json
from sqlalchemy import text as sql_text
from src.app.models.db import db_session
from fastapi.testclient import TestClient
from src.app.main import create_app


def test_explain_includes_cv_forensics_summary():
    prev_disable_ui = os.environ.get("DISABLE_UI_ROUTES")
    prev_db = os.environ.get("DATABASE_URL")
    os.environ["DISABLE_UI_ROUTES"] = "1"
    os.environ["DATABASE_URL"] = "sqlite:///test.sqlite"
    # Ensure decision reads are enabled for tests
    os.environ.setdefault("DECISION_LOG_WRITES_ENABLED", "1")
    try:
        app = create_app()
        client = TestClient(app)
        with db_session() as db:
            db.execute(sql_text("DROP TABLE IF EXISTS decision_logs"))
            db.execute(sql_text("DROP TABLE IF EXISTS evidence_bundles"))
            db.execute(sql_text("CREATE TABLE decision_logs (id TEXT PRIMARY KEY, agent_name TEXT, valid_from TEXT, input_data TEXT, retrieved_context TEXT, proposed_action TEXT, evaluator_model TEXT, created_at INTEGER)"))
            db.execute(sql_text("CREATE TABLE evidence_bundles (id TEXT, trace_id TEXT, bundle_json TEXT)"))
            db.execute(
                sql_text("INSERT OR REPLACE INTO decision_logs (id, agent_name, valid_from, input_data, retrieved_context, proposed_action, evaluator_model, created_at) VALUES (:id, :agent_name, :valid_from, :input_data, :retrieved_context, :proposed_action, :model, :created_at)"),
                {
                    "id": "t-123",
                    "agent_name": "cv_image_forensics",
                    "valid_from": "2026-01-01T00:00:00Z",
                    "input_data": json.dumps({"query": "refund", "intent": "complaint"}),
                    "retrieved_context": json.dumps({"agent_chain": ["cv_image_forensics"], "security_analysis": {"cvss_score": 2.5}}),
                    "proposed_action": json.dumps({"approve": True}),
                    "model": "model-x",
                    "created_at": 0,
                },
            )
            bundle = {
                "forensics": {
                    "verdict": "low-risk",
                    "manipulation_score": 0.1,
                    "blur_score": 0.2,
                    "metadata_flags": ["no_exif"],
                    "explanations": ["Image clean"],
                }
            }
            db.execute(sql_text("INSERT INTO evidence_bundles (id, trace_id, bundle_json) VALUES (:id, :trace_id, :bj)"), {"id": "b1", "trace_id": "t-123", "bj": json.dumps(bundle)})
            db.commit()
        # Directly call the explain handler (avoids router/auth complexity in unit test)
        import asyncio
        from src.app.routers.decisions import explain_decision
        with db_session() as read_db:
            result = asyncio.run(explain_decision("t-123", role="developer", db=read_db))
        assert result.get("decision_id") == "t-123"
        assert result.get("summary") is not None
    finally:
        if prev_disable_ui is None:
            os.environ.pop("DISABLE_UI_ROUTES", None)
        else:
            os.environ["DISABLE_UI_ROUTES"] = prev_disable_ui
        if prev_db is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev_db
