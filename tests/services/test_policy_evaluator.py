import uuid

from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.app.models.db import db_session, upsert
from src.app.services.policy_evaluator import PolicyEvaluator


def seed_control_rule(db, control_id: str, rule_id: str, rule_txt: str, tenant_id: str | None = None):
    upsert(
        db,
        "policy_graph_controls",
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
        "policy_graph_rules",
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
        db.execute("CREATE TABLE IF NOT EXISTS policy_graph_controls (id TEXT PRIMARY KEY, tenant_id TEXT, policy_id TEXT, control_key TEXT, enabled INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS policy_graph_rules (id TEXT PRIMARY KEY, control_id TEXT, rule TEXT, priority INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS policy_graph_evaluations (id TEXT PRIMARY KEY, decision_id TEXT, control_id TEXT, result TEXT, evaluated_at TEXT)")
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
    assert res == [{"control_id": "ctrl-1", "rule_id": "rule-1", "result": "fail"}]


def test_policy_evaluator_is_tenant_scoped_and_keeps_transaction_usable(tmp_path):
    import src.app.models.db as dbmod

    eng = create_engine(f"sqlite+pysqlite:///{tmp_path / 'policy.sqlite'}", future=True)
    set_engine = dbmod.set_engine
    set_engine(eng)
    dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    with db_session() as db:
        db.execute(
            text(
                "CREATE TABLE policy_graph_controls (id TEXT PRIMARY KEY, tenant_id TEXT, "
                "policy_id TEXT, control_key TEXT, enabled BOOLEAN)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE policy_graph_rules (id TEXT PRIMARY KEY, control_id TEXT, "
                "rule TEXT, priority INTEGER)"
            )
        )
        db.execute(
            text(
                "CREATE TABLE policy_graph_evaluations (id TEXT PRIMARY KEY, decision_id TEXT, "
                "control_id TEXT, result TEXT, evaluated_at TEXT)"
            )
        )
        seed_control_rule(db, "tenant-a-control", "tenant-a-rule", "ctx.risk:high", "tenant-a")
        seed_control_rule(db, "tenant-b-control", "tenant-b-rule", "ctx.risk:high", "tenant-b")
        db.commit()

    result = PolicyEvaluator().evaluate_and_persist(
        decision_id="decision-a",
        agent_name="test-agent",
        input_data={},
        retrieved_context={"risk": "high"},
        proposed_action={},
        tenant_id="tenant-a",
    )

    assert result == [
        {
            "control_id": "tenant-a-control",
            "rule_id": "tenant-a-rule",
            "result": "fail",
        }
    ]
    with db_session() as db:
        rows = db.execute(
            text("SELECT control_id FROM policy_graph_evaluations ORDER BY control_id")
        ).scalars().all()
        assert rows == ["tenant-a-control"]
