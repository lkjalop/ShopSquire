from contextlib import ExitStack
import gc
import weakref

import pytest
from sqlalchemy import create_engine, text

from src.app.models.database_ownership import database_owner, request_database_owner, RequestDatabaseUnavailable
from src.app.services.rule_store import RuleStore


def make_engine(label):
    engine = create_engine('sqlite+pysqlite:///:memory:')
    with engine.begin() as db:
        db.execute(text('''CREATE TABLE rule_definitions (
            id TEXT PRIMARY KEY, tenant_id TEXT, domain TEXT, title TEXT, pattern TEXT,
            expression TEXT, priority INTEGER, active BOOLEAN, created_by TEXT,
            version TEXT, effective_from TEXT, effective_to TEXT, created_at TEXT)'''))
        db.execute(text("INSERT INTO rule_definitions (id,tenant_id,domain,title,pattern,priority,active) "
                        "VALUES (:id,'same-tenant','recommend',:id,'private',1,true)"), {'id': label})
    return engine


def test_rule_cache_cannot_cross_runtime_database_owner():
    store = RuleStore()
    with ExitStack() as stack:
        engines = [make_engine('runtime-a'), make_engine('runtime-b')]
        for engine in engines:
            stack.callback(engine.dispose)
        for engine, expected in [(engines[0], 'runtime-a'), (engines[1], 'runtime-b'), (engines[0], 'runtime-a')]:
            with database_owner(engine):
                assert [rule['id'] for rule in store.get_active_rules('same-tenant')] == [expected]
        with request_database_owner(None), pytest.raises(RequestDatabaseUnavailable):
            store.get_active_rules('same-tenant')


def test_rule_cache_does_not_keep_retired_runtime_engine_alive():
    store = RuleStore()
    engine = make_engine('retired')
    reference = weakref.ref(engine)
    with database_owner(engine):
        assert store.get_active_rules('same-tenant')
    engine.dispose()
    del engine
    gc.collect()
    assert reference() is None
    assert len(store._cache) == 0
