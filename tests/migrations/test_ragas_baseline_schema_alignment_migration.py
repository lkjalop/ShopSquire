import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260832_ragas_baseline_schema_alignment.py"
    )
    spec = importlib.util.spec_from_file_location("ragas_baseline_alignment", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alignment_preserves_legacy_baseline_and_adds_timestamp():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE ragas_baseline "
                "(id TEXT PRIMARY KEY, baseline_score REAL)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO ragas_baseline (id, baseline_score) "
                "VALUES ('default', 0.75)"
            )
        )
        module = _migration()
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.upgrade()

        row = connection.execute(
            sa.text(
                "SELECT baseline_score, updated_at "
                "FROM ragas_baseline WHERE id='default'"
            )
        ).one()
        assert row[0] == 0.75
        assert row[1]


def test_alignment_creates_complete_table_when_missing():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        module = _migration()
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        connection.execute(
            sa.text(
                "INSERT INTO ragas_baseline (id, baseline_score) "
                "VALUES ('default', 0.8)"
            )
        )
        assert connection.execute(
            sa.text(
                "SELECT updated_at FROM ragas_baseline WHERE id='default'"
            )
        ).scalar_one()
