"""Security telemetry must not take ownership of a buyer transaction."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, create_engine, text
from sqlalchemy.orm import Session, declarative_base
from starlette.requests import Request

from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id
from src.app.security import observer


@pytest.fixture
def observer_database(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'observer.sqlite3'),
                           connect_args={'timeout': 0.1})
    with engine.begin() as db:
        db.execute(text('CREATE TABLE security_events (id TEXT PRIMARY KEY, path TEXT, '
            'event_time TEXT, severity TEXT, verdict_score INTEGER, details TEXT)'))
        db.execute(text('CREATE TABLE security_observer_timeseries (id TEXT PRIMARY KEY, '
            'event_id TEXT,severity TEXT,risk_adj REAL,insider_score REAL,tenant_id TEXT)'))
        db.execute(text('CREATE TABLE business_transaction (id INTEGER PRIMARY KEY)'))
    monkeypatch.setenv('SECURITY_OBSERVER_SYNC', '1')
    monkeypatch.setenv('SECURITY_OBSERVER_SAMPLE_RATE', '1')
    monkeypatch.setenv('SKIP_OBSERVER_ENDPOINTS', '')
    monkeypatch.setattr(observer, 'auto_route_security_event', lambda *args: None)
    monkeypatch.setattr(observer, 'append_worm_record', lambda *args: None)
    yield engine
    engine.dispose()


def test_observer_never_flushes_or_commits_request_business_work(observer_database):
    engine = observer_database
    base = declarative_base()

    class Business(base):
        __tablename__ = 'business_transaction'
        id = Column(Integer, primary_key=True)

    with Session(engine) as caller:
        caller.add(Business(id=42))
        request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(engine=engine)),
                           'state': {'db': caller}, 'headers': [], 'client': ('127.0.0.1', 1)})
        observer.emit_security_event('/ownership', {'analysis': {'severity': 'info', 'risk_adj': 0}}, request=request)
        assert len(caller.new) == 1, 'Observer must not flush caller-owned pending business work'
        caller.rollback()
    with engine.connect() as db:
        assert db.execute(text('SELECT count(*) FROM business_transaction')).scalar_one() == 0
        assert db.execute(text('SELECT count(*) FROM security_events')).scalar_one() == 1


def test_observer_timeseries_uses_the_same_engine_and_captured_tenant(observer_database):
    engine = observer_database
    request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(engine=engine)),
                       'state': {}, 'headers': [], 'client': ('127.0.0.1', 1)})
    token = set_active_tenant_id('observer-owned-tenant')
    try:
        observer.emit_security_event('/ownership', {'analysis': {'severity': 'info', 'risk_adj': 0}}, request=request)
    finally:
        reset_active_tenant_id(token)
    with engine.connect() as db:
        event = db.execute(text('SELECT id,details FROM security_events')).one()
        point = db.execute(text('SELECT event_id,tenant_id FROM security_observer_timeseries')).one()
        assert point == (event.id, 'observer-owned-tenant')
        assert json.loads(event.details)['analysis']['severity'] == 'info'


def test_async_observer_captures_identity_without_retaining_the_request(observer_database, monkeypatch):
    import gc
    import threading
    import weakref

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setenv('SECURITY_OBSERVER_SYNC', '0')

    def delayed_risk(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return 'info', 0, 0, {'severity': 'info'}

    monkeypatch.setattr(observer, 'compute_risk', delayed_risk)
    monkeypatch.setattr(observer, 'append_worm_record', lambda *args: finished.set())
    request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(engine=observer_database)),
                       'state': {}, 'headers': [], 'client': ('127.0.0.1', 1)})
    reference = weakref.ref(request)
    token = set_active_tenant_id('async-owned-tenant')
    try:
        observer.emit_security_event('/async-ownership', {'message': 'ordinary event'}, request=request)
    finally:
        reset_active_tenant_id(token)
    try:
        assert entered.wait(3)
        del request
        gc.collect()
        assert reference() is None, 'A slow telemetry worker must not retain a request or its session'
    finally:
        release.set()
        assert finished.wait(3)
    with observer_database.connect() as db:
        assert db.execute(text('SELECT tenant_id FROM security_observer_timeseries')).scalar_one() == 'async-owned-tenant'


def test_failed_primary_insert_does_not_claim_a_persisted_security_event(observer_database, monkeypatch):
    effects = []
    monkeypatch.setattr(observer, 'auto_route_security_event', lambda *args: effects.append('route'))
    monkeypatch.setattr(observer, 'append_worm_record', lambda *args: effects.append('worm'))
    with observer_database.begin() as db:
        db.execute(text('DROP TABLE security_events'))
    request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(engine=observer_database)),
                       'state': {}, 'headers': [], 'client': ('127.0.0.1', 1)})
    observer.emit_security_event('/failed-primary', {'analysis': {'severity': 'info', 'risk_adj': 0}}, request=request)
    assert effects == [], 'A rolled-back insert cannot be routed as a persisted event'


def test_shared_sqlite_connection_cannot_commit_a_callers_active_transaction(monkeypatch):
    from sqlalchemy.pool import StaticPool
    engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
    with engine.begin() as db:
        db.execute(text('CREATE TABLE business_transaction (id INTEGER PRIMARY KEY)'))
        db.execute(text('CREATE TABLE security_events (id TEXT PRIMARY KEY,path TEXT,event_time TEXT,'
                        'severity TEXT,verdict_score INTEGER,details TEXT)'))
        db.execute(text('CREATE TABLE security_observer_timeseries (id TEXT,event_id TEXT,severity TEXT,'
                        'risk_adj REAL,insider_score REAL,tenant_id TEXT)'))
    monkeypatch.setenv('SECURITY_OBSERVER_SYNC', '1')
    monkeypatch.setenv('SECURITY_OBSERVER_SAMPLE_RATE', '1')
    monkeypatch.setattr(observer, 'auto_route_security_event', lambda *args: None)
    monkeypatch.setattr(observer, 'append_worm_record', lambda *args: None)
    try:
        with Session(engine) as caller:
            caller.execute(text('INSERT INTO business_transaction VALUES (42)'))
            request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(engine=engine)),
                               'state': {'db': caller}, 'headers': [], 'client': ('127.0.0.1', 1)})
            observer.emit_security_event('/shared-ownership', {'analysis': {'severity': 'info', 'risk_adj': 0}}, request=request)
            caller.rollback()
        with engine.connect() as db:
            assert db.execute(text('SELECT count(*) FROM business_transaction')).scalar_one() == 0
            assert db.execute(text('SELECT count(*) FROM security_events')).scalar_one() == 1
    finally:
        engine.dispose()
