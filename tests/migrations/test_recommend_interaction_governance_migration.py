import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_migration_creates_authoritative_tenant_and_consent_columns():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    path = ROOT / "alembic" / "versions" / "20260726_recommend_interaction_governance.py"
    spec = importlib.util.spec_from_file_location("interaction_governance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.upgrade()

    columns = {column["name"]: column for column in inspect(engine).get_columns(
        "recommend_interactions")}
    assert columns["tenant_id"]["nullable"] is False
    assert columns["consent_state"]["nullable"] is False
    assert "ix_recommend_interactions_tenant_time" in {
        index["name"] for index in inspect(engine).get_indexes("recommend_interactions")
    }
