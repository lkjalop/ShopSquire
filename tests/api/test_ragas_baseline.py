import os
import json
from sqlalchemy import text as sql_text
from src.app.models.db import db_session
from src.app.services.ragas_eval import ci_guard_check, evaluate_and_persist


def test_ragas_baseline_gauges_init_and_update():
    os.environ.setdefault("DATABASE_URL", "sqlite:///test.sqlite")
    # Seed minimal decision record
    import time
    with db_session() as db:
        db.execute(sql_text("CREATE TABLE IF NOT EXISTS decision_logs (id TEXT PRIMARY KEY, agent_name TEXT NOT NULL, input_data TEXT, retrieved_context TEXT, proposed_action TEXT, evaluator_model TEXT, created_at INTEGER)"))
        db.execute(sql_text("CREATE TABLE IF NOT EXISTS ragas_eval_results (eval_id TEXT, decision_log_id TEXT, faithfulness REAL, answer_relevance REAL, context_precision REAL, context_recall REAL, evaluator_model TEXT, created_at INTEGER DEFAULT (strftime('%s','now')))"))
        db.execute(sql_text("CREATE TABLE IF NOT EXISTS ragas_baseline (id TEXT PRIMARY KEY, baseline_score REAL)"))
        ts = int(time.time())
        db.execute(
            sql_text("INSERT OR REPLACE INTO decision_logs (id, agent_name, input_data, retrieved_context, proposed_action, evaluator_model, created_at) VALUES (:id, :agent_name, :input_data, :retrieved_context, :proposed_action, :model, :created_at)"),
            {
                "id": "d1",
                "agent_name": "ragas_eval",
                "input_data": json.dumps({"query": "q"}),
                "retrieved_context": json.dumps({"order": 1}),
                "proposed_action": json.dumps({"a": 1}),
                "model": "model-x",
                "created_at": ts,
            },
        )
        db.commit()
    # Evaluate once -> initializes baseline
    res = evaluate_and_persist("d1")
    assert res.get("evaluated") is True
    # CI guard should report baseline initialized or ok
    guard = ci_guard_check()
    assert "baseline" in guard or guard.get("ok") is True
