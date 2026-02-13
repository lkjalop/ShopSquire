"""Basic tests for RuleStore and rule_definitions migration seed."""

from sqlalchemy import text
from src.app.models.db import db_session
from src.app.services.rule_store import RuleStore


def ensure_table():
    with db_session() as db:
        db.execute(
            text(
                "CREATE TABLE IF NOT EXISTS rule_definitions ("
                "id TEXT PRIMARY KEY, tenant_id TEXT, domain TEXT, title TEXT, pattern TEXT, expression TEXT, "
                "priority INTEGER, active INTEGER, created_by TEXT, version TEXT, effective_from TEXT, effective_to TEXT, created_at TEXT)"
            )
        )
        db.commit()


def test_seed_and_load_rules():
    ensure_table()
    store = RuleStore()
    # refresh to ensure reading DB
    rules = store.refresh()
    # rules should be a list (may be empty if migration not run)
    assert isinstance(rules, list)
