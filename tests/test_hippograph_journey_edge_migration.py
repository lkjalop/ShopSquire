import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration_module():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260863_hippograph_journey_edges.py"
    spec = importlib.util.spec_from_file_location("hippograph_edge_migration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_adopts_compatible_legacy_table_and_adds_index(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    migration = _migration_module()
    metadata = sa.MetaData()
    columns = []
    nullable = {"case_id", "valid_to", "supersedes_edge_id"}
    for name in sorted(migration._EXPECTED_COLUMNS):
        column_type = sa.Integer() if name == "confidence_micros" else sa.Text()
        columns.append(sa.Column(name, column_type, primary_key=name == "id", nullable=name in nullable))
    sa.Table(
        "hippograph_journey_edges",
        metadata,
        *columns,
        sa.UniqueConstraint("tenant_id", "edge_id", name="uq_hippograph_journey_edge_tenant"),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

    inspector = sa.inspect(engine)
    assert "ix_hippograph_journey_case_time" in {
        row["name"] for row in inspector.get_indexes("hippograph_journey_edges")
    }
