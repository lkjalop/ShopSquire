from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_executive_metric_contract_is_portable_and_idempotent():
    path = (Path(__file__).resolve().parents[2] / "alembic" / "versions" /
            "20260725_executive_metric_contract.py")
    spec = spec_from_file_location("executive_metric_contract", path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        tables = set(inspect(connection).get_table_names())
        assert "executive_metric_snapshot" in tables
        assert "supplier_score_audits" in tables
        columns = {row["name"] for row in inspect(connection).get_columns(
            "executive_metric_snapshot")}
        assert {"tenant_id", "status", "visibility", "provenance_json"} <= columns
