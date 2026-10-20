"""Apply an actual Alembic revision to a minimal isolated test engine."""
import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations


def apply_revision(engine, filename):
    path=Path(__file__).resolve().parents[1]/'alembic'/'versions'/filename
    spec=importlib.util.spec_from_file_location('isolated_fixture_revision',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
