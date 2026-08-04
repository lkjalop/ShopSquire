from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260825_tenant_experiment_policy.py"
)


def test_migration_scopes_experiments_and_seals_legacy_policy():
    spec = importlib.util.spec_from_file_location("tenant_experiment_policy", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE experiment_run ("
            "id TEXT PRIMARY KEY, name TEXT, target_metric TEXT, status TEXT, "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP, started_at TEXT, ended_at TEXT)"
        ))
        connection.execute(text(
            "CREATE TABLE experiment_assignment ("
            "id TEXT PRIMARY KEY, experiment_id TEXT, subject_hash TEXT, variant TEXT, assigned_at TEXT)"
        ))
        connection.execute(text(
            "CREATE TABLE experiment_result ("
            "id TEXT PRIMARY KEY, experiment_id TEXT, variant TEXT, decision TEXT, "
            "uplift_pct REAL, evidence_json TEXT, decided_at TEXT)"
        ))
        connection.execute(text(
            "INSERT INTO experiment_run (id,name,target_metric,status) "
            "VALUES ('e1','ranking','conversion','draft')"
        ))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        row = connection.execute(text(
            "SELECT tenant_id, policy_json, policy_version FROM experiment_run WHERE id='e1'"
        )).fetchone()
        assert row[0] == "default"
        assert json.loads(row[1])["baseline"]["legacy_unsealed"] is True
        assert row[2] == "experiment-policy.v1"

    assert {"tenant_id", "policy_json", "policy_version"} <= {
        column["name"] for column in inspect(engine).get_columns("experiment_run")
    }
    assert "tenant_id" in {
        column["name"] for column in inspect(engine).get_columns("experiment_assignment")
    }
    indexes = {index["name"] for index in inspect(engine).get_indexes("experiment_run")}
    assert {"ux_experiment_tenant_name", "ix_experiment_tenant_status"} <= indexes
