"""Actual startup/shutdown must use the serving application's database."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from src.app.models import db as database
from src.app.models.database_ownership import current_database_engine


@pytest.mark.parametrize('foreign_default', [False, True])
@pytest.mark.parametrize('startup_failure', [False, True])
@pytest.mark.parametrize('phase', ['startup', 'shutdown'])
def test_application_lifespan_keeps_its_database_owner(monkeypatch, tmp_path, foreign_default, startup_failure, phase):
    from src.app import main
    original = database.get_engine()
    original_factory = database.SessionLocal
    url = 'sqlite+pysqlite:///' + (tmp_path / 'serving.sqlite3').as_posix()
    foreign = database.create_runtime_engine('sqlite+pysqlite:///' + (tmp_path / 'foreign.sqlite3').as_posix())
    monkeypatch.setenv('DATABASE_URL', url)
    monkeypatch.setenv('DATABASE_URL_RO', url)
    monkeypatch.setenv('FEATURE_FLAGS_PATH', str(tmp_path / 'flags.json'))
    app = getattr(main, '_original_create_app', main.create_app)()
    serving = app.state.engine
    app.state.owns_engine = True  # Transfer this test-created application's engine to its lifespan.
    selected_default = foreign if foreign_default else serving
    database.set_engine(selected_default)
    observed = []
    disposed = []
    actual_step = main.run_startup_step

    def record_step(application, **kwargs):
        engine = database.get_engine()
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT 1')) == 1
        observed.append((kwargs['name'], engine, current_database_engine()))
        if startup_failure and kwargs['name'] == 'database_migrations':
            raise RuntimeError('controlled_required_startup_failure')
        return actual_step(application, **kwargs)

    def record_disposal(_engine):
        disposed.append((database.get_engine(), current_database_engine()))

    monkeypatch.setattr(main, 'run_startup_step', record_step)
    event.listen(serving, 'engine_disposed', record_disposal)
    try:
        if startup_failure:
            with pytest.raises(RuntimeError, match='controlled_required_startup_failure'):
                with TestClient(app):
                    pytest.fail('failed required startup must not yield a client')
        else:
            with TestClient(app) as client:
                assert client.get('/healthz').status_code == 200
        assert observed
        if phase == 'startup':
            assert all(engine is serving and owner is serving for _, engine, owner in observed), 'startup_used_foreign_database_owner'
        else:
            assert disposed == [(serving, serving)], 'shutdown_used_foreign_database_owner'
        assert database.get_engine() is selected_default
        assert current_database_engine() is None
    finally:
        event.remove(serving, 'engine_disposed', record_disposal)
        database.set_engine(original)
        database.SessionLocal = original_factory
        serving.dispose()
        foreign.dispose()
