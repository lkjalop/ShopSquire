import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import set_engine
from src.app.models.init_db import ensure_metadata
from src.app.services.decision_log import log_decision


def test_log_decision_adds_dynamic_decision_tags(tmp_path, monkeypatch):
    db_path = tmp_path / "decision_tags.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    ensure_metadata()
    dec_id = log_decision(
        agent_name="recommendation_agent",
        input_data={"query": "laptop under 1500"},
        retrieved_context={"security": {"severity": "info"}, "candidates": [{"sku": "A"}]},
        proposed_action={"ranked_skus": ["A", "B"], "reasons": ["within_budget"]},
        policy_version="v1",
        execution_status="executed",
    )
    with eng.connect() as conn:
        row = conn.execute(text("SELECT proposed_action FROM decision_logs WHERE id = :id"), {"id": dec_id}).fetchone()
    assert row is not None
    action = json.loads(row[0] or "{}")
    tags = action.get("decision_tags") or []
    assert "has_query" in tags
    assert "candidate_context" in tags
    assert "ranked_output" in tags
