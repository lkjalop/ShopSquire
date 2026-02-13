"""Integration test: ExpandedRuleEngine should load DB rules and classify sample queries."""

import os
from src.app.services.expanded_rules import ExpandedRuleEngine
from src.app.services.rule_store import RuleStore
from src.app.models.db import db_session, upsert, set_engine
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text


def ensure_table_and_seed():
    # Force lightweight SQLite for ad-hoc table creation in this test and patch engine
    os.environ.setdefault("DATABASE_URL", "sqlite://")
    eng = create_engine("sqlite://", future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    with db_session() as db:
        db.execute(
            text(
                "CREATE TABLE IF NOT EXISTS rule_definitions ("
                "id TEXT PRIMARY KEY, tenant_id TEXT, domain TEXT, title TEXT, pattern TEXT, expression TEXT, "
                "priority INTEGER, active INTEGER, created_by TEXT, version TEXT, effective_from TEXT, effective_to TEXT, created_at TEXT)"
            )
        )
        # seed a simple rule via dialect-aware upsert
        upsert(
            db,
            "rule_definitions",
            {
                "id": "r_test_search",
                "tenant_id": None,
                "domain": "recommend",
                "title": "product_search",
                "pattern": "show\\s+me|find|search\\s+for",
                "priority": 10,
                "active": True,
                "created_by": "test",
                "version": "v1",
                "created_at": "CURRENT_TIMESTAMP",
            },
            ["id"],
        )
        db.commit()


def test_expanded_engine_loads_db_rules():
    ensure_table_and_seed()
    store = RuleStore()
    engine = ExpandedRuleEngine(rule_store=store)
    res = engine.evaluate("show me laptops", {"memory": {}, "live": {}})
    assert isinstance(res, dict)
    assert res.get("handled") is True
    assert res.get("intent") == 'product_search' or 'product_search' in str(res.get('intent'))
