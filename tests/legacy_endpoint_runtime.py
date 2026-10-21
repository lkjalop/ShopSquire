"""A request lifetime over one explicitly owned, migrated disposable database."""
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from src.app.main import create_app
from src.app.models.db import create_runtime_engine, get_engine, set_engine
from src.app.models.database_ownership import database_owner
from tests.utils import default_headers


@pytest.fixture
def endpoint_runtime(monkeypatch, tmp_path):
    original_engine = get_engine()
    database_url = 'sqlite+pysqlite:///' + (tmp_path / 'endpoint.sqlite3').as_posix()
    engine = create_runtime_engine(database_url)
    monkeypatch.setenv('DATABASE_URL', database_url)
    monkeypatch.setenv('DATABASE_URL_RO', database_url)
    monkeypatch.setenv('FEATURE_FLAGS_PATH', str(tmp_path / 'flags.json'))
    monkeypatch.setenv('SECURITY_OBSERVER_SYNC', '1')
    monkeypatch.setenv('SECURITY_BLOCK_MODE', '200')
    monkeypatch.setenv('SKIP_OBSERVER_ENDPOINTS', '')
    try:
        command.upgrade(Config('alembic.ini'), 'head')
        set_engine(engine)
        app = create_app()
        created_engine = getattr(app.state, 'engine', None)
        if getattr(app.state, 'owns_engine', False) and created_engine is not engine and created_engine is not None:
            created_engine.dispose()
        app.state.engine = engine
        app.state.owns_engine = False
        with database_owner(engine), TestClient(app, headers=default_headers()) as client:
            yield engine, client
    finally:
        set_engine(original_engine)
        engine.dispose()
