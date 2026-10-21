"""A catalog fixture cannot be replaced by an ambient engine during app creation."""
from sqlalchemy import create_engine

from src.app.models import db as database
from src.app.models.database_ownership import database_owner
from src.app.models.orm import Base
from tests.integration import test_frontend_backend_parity as parity
from tests.integration.test_frontend_backend_parity import _seed, _contract_router
from tests.v2_catalog_fixture import grounded_v2_catalog


def test_parity_fixture_uses_runtime_journal_policy_and_migrated_schema():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    with database.get_engine().connect() as connection:
        assert connection.scalar(text('PRAGMA journal_mode')) == 'wal'
        actual_heads = set(connection.scalars(text('SELECT version_num FROM alembic_version')))
    assert actual_heads == set(ScriptDirectory.from_config(Config('alembic.ini')).get_heads())


def test_parity_request_uses_its_seeded_catalog_when_factory_changes_global_engine(monkeypatch, tmp_path):
    seeded_engine = database.get_engine()
    foreign = create_engine(f"sqlite+pysqlite:///{tmp_path / 'foreign-catalog.sqlite3'}")
    Base.metadata.create_all(foreign)
    catalog = grounded_v2_catalog(
        [('FOREIGN-PARITY-CANARY', 'Alternate business laptop', 109900, 4,
          {'ram_gb': 16, 'storage_gb': 1024})],
        node_handle='el-6-6', source='foreign-parity-control')
    with database_owner(foreign):
        catalog.__enter__()
    original_factory = parity.create_app

    def create_and_change_ambient_engine():
        app = original_factory()
        database.set_engine(foreign)
        return app

    monkeypatch.setattr(parity, 'create_app', create_and_change_ambient_engine)
    try:
        result = parity._suggest('owned-parity-control', 'show me laptops under 1500')
        skus = {row['sku'] for row in result.get('results') or []}
        assert skus
        assert skus <= {'FBP-1', 'FBP-2', 'FBP-3'}
        assert 'FOREIGN-PARITY-CANARY' not in skus
    finally:
        database.set_engine(seeded_engine)
        with database_owner(foreign):
            catalog.__exit__(None, None, None)
        foreign.dispose()
