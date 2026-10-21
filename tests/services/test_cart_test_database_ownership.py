"""The cart HTTP fixture must support independent request/observer transactions."""
from sqlalchemy import text
from sqlalchemy.orm import Session
import pytest

from tests.test_cart_stock_gates import client_with_stock


def test_secondary_session_rollback_cannot_undo_a_cart_fixture_transaction(client_with_stock):
    engine = client_with_stock.app.state.engine
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE fixture_transaction_owner_probe(value INTEGER)'))
    with Session(engine) as writer, Session(engine) as observer:
        writer.execute(text('INSERT INTO fixture_transaction_owner_probe VALUES (1)'))
        observed_before_commit = observer.execute(text('SELECT COUNT(*) FROM fixture_transaction_owner_probe')).scalar_one()
        observer.rollback()
        writer.commit()
    with engine.connect() as connection:
        persisted_after_commit = connection.execute(text('SELECT COUNT(*) FROM fixture_transaction_owner_probe')).scalar_one()
    assert (observed_before_commit, persisted_after_commit) == (0, 1)


def test_cart_fixture_restores_global_owner_and_disposes_engine_if_app_setup_fails(monkeypatch, tmp_path):
    from tests import test_cart_stock_gates as fixture_module
    from src.app.models import db as database
    from src.app import main

    original_owner = database.engine
    original_factory = fixture_module._make_engine
    owned = []
    disposed = []

    def create_owned(url):
        engine = original_factory(url)
        original_dispose = engine.dispose
        owned.append((engine, original_dispose))
        def dispose():
            disposed.append(engine)
            original_dispose()
        monkeypatch.setattr(engine, 'dispose', dispose)
        return engine

    def failed_application():
        raise RuntimeError('injected_application_setup_failure')

    monkeypatch.setattr(fixture_module, '_make_engine', create_owned)
    monkeypatch.setattr(main, 'create_app', failed_application)
    fixture = fixture_module.client_with_stock.__wrapped__(monkeypatch, tmp_path)
    try:
        with pytest.raises(RuntimeError, match='injected_application_setup_failure'):
            next(fixture)
        assert database.engine is original_owner
        assert disposed == [owned[0][0]]
    finally:
        database.engine = original_owner
        database.set_engine(original_owner)
        for _engine, original_dispose in owned:
            original_dispose()
