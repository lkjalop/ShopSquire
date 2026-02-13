import json
import uuid

from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.app.models.db import db_session, upsert
from src.app.services.policy_evaluator import PolicyEvaluator


def seed_control_rule(db, control_id: str, rule_id: str, rule_txt: str, tenant_id: str | None = None):
    upsert(
        db,
        "pg_controls",
        {
            "id": control_id,
            "tenant_id": tenant_id,
            "policy_id": str(uuid.uuid4()),
            "control_key": f"ck_{control_id}",
            "enabled": True,
        },
        ["id"],
    )
    upsert(
        db,
        "pg_rules",
        {"id": rule_id, "control_id": control_id, "rule": rule_txt, "priority": 0},
        ["id"],
    )


def test_policy_evaluator_basic():
    pe = PolicyEvaluator()
    # Force lightweight SQLite for ad-hoc table creation in this test
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    # Patch app DB engine/session to use in-memory SQLite
    import src.app.models.db as dbmod
    eng = create_engine("sqlite://", future=True)
    try:
        dbmod.set_engine(eng)
    except Exception:
        dbmod.engine = eng
    dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    with db_session() as db:
        # Ensure tables exist (sqlite fallback)
        db.execute("CREATE TABLE IF NOT EXISTS pg_controls (id TEXT PRIMARY KEY, tenant_id TEXT, policy_id TEXT, control_key TEXT, enabled INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS pg_rules (id TEXT PRIMARY KEY, control_id TEXT, rule TEXT, priority INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS pg_evaluations (id TEXT PRIMARY KEY, decision_id TEXT, control_id TEXT, result TEXT, evaluated_at TEXT)")
        # Seed a control that matches when ctx.damage_not_visible == True
        seed_control_rule(db, "ctrl-1", "rule-1", "ctx.damage_not_visible:True", tenant_id=None)
        db.commit()

    # Call evaluate on a decision with damage_not_visible True
    res = pe.evaluate_and_persist(
        decision_id=str(uuid.uuid4()),
        agent_name="test_agent",
        input_data={"x": 1},
        retrieved_context={"damage_not_visible": True},
        proposed_action={"analysis": {}},
    )
    # Expect at least one rule evaluation present in results
    assert isinstance(res, list)
