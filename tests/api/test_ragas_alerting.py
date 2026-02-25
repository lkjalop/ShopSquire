from __future__ import annotations

import json
import time

from sqlalchemy import text as sql_text

from src.app.models.db import db_session
from src.app.services.ragas_eval import ci_guard_check


def test_ragas_ci_guard_detects_drop_with_baseline():
    with db_session() as db:
        db.execute(sql_text("CREATE TABLE IF NOT EXISTS ragas_eval_results (eval_id TEXT, decision_log_id TEXT, faithfulness REAL, answer_relevance REAL, context_precision REAL, context_recall REAL, evaluator_model TEXT, created_at INTEGER DEFAULT (strftime('%s','now')))"))
        db.execute(sql_text("CREATE TABLE IF NOT EXISTS ragas_baseline (id TEXT PRIMARY KEY, baseline_score REAL)"))
        db.execute(sql_text("INSERT OR REPLACE INTO ragas_baseline (id, baseline_score) VALUES ('default', 0.9)"))
        now = int(time.time())
        for i in range(40):
            db.execute(
                sql_text("INSERT INTO ragas_eval_results (eval_id, decision_log_id, faithfulness, answer_relevance, context_precision, context_recall, evaluator_model, created_at) VALUES (:eid, :did, :f, :ar, :cp, :cr, :m, :ts)"),
                {"eid": f"e{i}", "did": "d1", "f": 0.4, "ar": 0.5, "cp": 0.4, "cr": 0.4, "m": "m", "ts": now - i},
            )
        db.commit()
    out = ci_guard_check(window=40, drop_pct=0.1)
    assert out.get("ok") is False
    assert out.get("reason") == "moving_avg_drop"
