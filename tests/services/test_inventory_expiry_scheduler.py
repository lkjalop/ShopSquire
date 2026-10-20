from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from threading import Event
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from tests.services.test_inventory_expiry import NOW, reserve
from tests.services.test_inventory_transactions import engine, stock
from src.app.services import inventory_expiry_scheduler as scheduler


def test_scheduled_batch_commits_expiry_and_replay_has_no_effect(engine):
    with Session(engine) as db:
        reserve(db);db.commit()
    @contextmanager
    def factory():
        with Session(engine) as db:yield db
    assert scheduler.run_once(session_factory=factory,now=NOW+timedelta(hours=1))['expired']==1
    assert scheduler.run_once(session_factory=factory,now=NOW+timedelta(hours=1))['expired']==0
    with Session(engine) as db:assert stock(db)==(15,0,15)


def test_worker_is_opt_in_and_stops_without_orphan(monkeypatch):
    app=SimpleNamespace(state=SimpleNamespace(engine=object()))
    monkeypatch.setenv('INVENTORY_EXPIRY_SCHEDULER_ENABLED','0')
    scheduler.start_inventory_expiry_scheduler(app)
    assert not hasattr(app.state,'inventory_expiry_thread')
    called=Event()
    monkeypatch.setattr(scheduler,'run_once',lambda **kwargs: called.set())
    monkeypatch.setenv('INVENTORY_EXPIRY_SCHEDULER_ENABLED','1')
    scheduler.start_inventory_expiry_scheduler(app)
    assert called.wait(2)
    scheduler.stop_inventory_expiry_scheduler(app)
    assert not app.state.inventory_expiry_thread.is_alive()


def test_worker_uses_its_app_database_after_global_owner_changes(engine, tmp_path, monkeypatch):
    with Session(engine) as db:
        reserve(db)
        db.commit()
    foreign = create_engine('sqlite:///' + str(tmp_path / 'foreign.sqlite3'))
    app = SimpleNamespace(state=SimpleNamespace(engine=engine))
    completed = Event()
    real_run = scheduler.run_once
    errors = []

    def observe(**kwargs):
        try:
            return real_run(now=NOW + timedelta(hours=1), **kwargs)
        except Exception as error:
            errors.append(type(error).__name__)
            raise
        finally:
            completed.set()

    @contextmanager
    def foreign_session():
        with Session(foreign) as db:
            yield db

    monkeypatch.setattr(scheduler, 'run_once', observe)
    monkeypatch.setattr(scheduler, 'db_session', foreign_session)
    monkeypatch.setenv('INVENTORY_EXPIRY_SCHEDULER_ENABLED', '1')
    try:
        scheduler.start_inventory_expiry_scheduler(app)
        assert completed.wait(3), 'App-owned expiry pass did not complete'
        scheduler.stop_inventory_expiry_scheduler(app)
        assert errors == []
        with Session(engine) as db:
            assert stock(db) == (15, 0, 15)
        assert not app.state.inventory_expiry_thread.is_alive()
    finally:
        scheduler.stop_inventory_expiry_scheduler(app)
        foreign.dispose()


def test_enabled_worker_requires_database_owner_before_allocating_a_thread(monkeypatch):
    monkeypatch.setenv('INVENTORY_EXPIRY_SCHEDULER_ENABLED', '1')
    app = SimpleNamespace(state=SimpleNamespace())
    try:
        with pytest.raises(RuntimeError, match='database owner'):
            scheduler.start_inventory_expiry_scheduler(app)
    finally:
        scheduler.stop_inventory_expiry_scheduler(app)


def test_shutdown_does_not_report_success_while_worker_remains_alive():
    class InFlightThread:
        def join(self, timeout):
            assert timeout == 5

        def is_alive(self):
            return True

    stop = Event()
    app = SimpleNamespace(state=SimpleNamespace(inventory_expiry_stop=stop,
                                               inventory_expiry_thread=InFlightThread()))
    with pytest.raises(RuntimeError, match='did not stop'):
        scheduler.stop_inventory_expiry_scheduler(app)
    assert stop.is_set()
