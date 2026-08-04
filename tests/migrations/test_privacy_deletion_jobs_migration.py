import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_privacy_deletion_job_schema_is_tenant_scoped():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260830_privacy_deletion_jobs.py"
    )
    spec = importlib.util.spec_from_file_location("privacy_deletion_jobs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.upgrade()

    columns = {
        column["name"]: column
        for column in sa.inspect(engine).get_columns("privacy_deletion_job")
    }
    assert columns["tenant_id"]["nullable"] is False
    assert columns["subject_hash"]["nullable"] is False
    assert "subject_id" not in columns
