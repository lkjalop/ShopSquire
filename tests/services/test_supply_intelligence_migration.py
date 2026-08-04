from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260817_supply_intelligence.py"
)


def test_supply_intelligence_migration_is_idempotent_and_retains_evidence_on_downgrade():
    spec = importlib.util.spec_from_file_location("supply_intelligence_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.upgrade()
        expected = {
            "supply_node",
            "supply_dependency_edge",
            "supply_signal_observation",
            "causal_impact_hypothesis",
            "procurement_option_proposal",
            "synthetic_supply_scenario_manifest",
        }
        assert expected <= set(inspect(connection).get_table_names())
        module.downgrade()
        assert expected <= set(inspect(connection).get_table_names())
