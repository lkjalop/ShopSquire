"""Contract checks must not replace a cached app's engine or lose their catalog."""
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.main import create_app
from src.app.models import db as database
from src.app.models.db import get_engine, set_engine
from tests import conftest as runtime
from tests.integration.test_recommend_contract_stability import (
    _CONTRACT_SKU, _ground_v2_contract_catalog, _suggest,
)


@pytest.fixture(scope='module', autouse=True)
def prior_cached_owner(tmp_path_factory):
    original = get_engine()
    original_factory = database.SessionLocal
    with runtime._SINGLETONS_LOCK:
        prior_apps = [(app, app.state.engine, app.state.owns_engine)
                      for app in runtime._session_applications()]
    directory = tmp_path_factory.mktemp('prior-contract-owner')
    url = 'sqlite+pysqlite:///' + (directory / 'owner.sqlite3').as_posix()
    app = engine = None
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('DATABASE_URL', url)
        patch.setenv('DATABASE_URL_RO', url)
        try:
            app = create_app()
            engine = app.state.engine
            assert app.state.owns_engine is True, 'The control requires a real factory-owned cached app'
            with engine.begin() as db:
                db.execute(text('CREATE TABLE fixture_owner_canary(value INTEGER)'))
                db.execute(text('INSERT INTO fixture_owner_canary VALUES (17)'))
            yield app, engine
        finally:
            with runtime._SINGLETONS_LOCK:
                if runtime._SINGLETONS.get(url) is app:
                    runtime._SINGLETONS.pop(url)
                for prior_app, prior_engine, prior_ownership in prior_apps:
                    prior_app.state.engine = prior_engine
                    prior_app.state.owns_engine = prior_ownership
            set_engine(original)
            database.SessionLocal = original_factory
            if engine is not None:
                engine.dispose()


def test_contract_calls_preserve_the_cached_owner_and_the_current_catalog(prior_cached_owner):
    cached, cached_engine = prior_cached_owner
    borrowed = get_engine()
    assert borrowed is not cached_engine
    first = _suggest('contract-owner-first', 'gaming laptop under 1800')
    assert isinstance(first.get('right_panel'), dict)
    assert cached.state.engine is cached_engine, 'Contract fixture replaced another cached application owner'
    with cached_engine.connect() as db:
        assert db.scalar(text('SELECT value FROM fixture_owner_canary')) == 17
    with borrowed.connect() as db:
        assert db.scalar(text('SELECT COUNT(*) FROM products WHERE sku=:sku'), {'sku': _CONTRACT_SKU}) == 1
        assert db.scalar(text('PRAGMA journal_mode')) == 'wal'
        assert set(db.scalars(text('SELECT version_num FROM alembic_version'))) == set(
            ScriptDirectory.from_config(Config('alembic.ini')).get_heads())
    with Session(borrowed) as pending:
        pending.execute(text('UPDATE products SET price_cents=199999 WHERE sku=:sku'), {'sku': _CONTRACT_SKU})
        with borrowed.connect() as observer:
            assert observer.scalar(text('SELECT price_cents FROM products WHERE sku=:sku'), {'sku': _CONTRACT_SKU}) == 149900
        pending.rollback()
    second = _suggest('contract-owner-second', 'gaming laptop under 1800')
    assert isinstance(second.get('right_panel'), dict)
    assert 'anchor_sections' in second['right_panel']
    with borrowed.connect() as db:
        assert db.scalar(text('SELECT COUNT(*) FROM products WHERE sku=:sku'), {'sku': _CONTRACT_SKU}) == 1
