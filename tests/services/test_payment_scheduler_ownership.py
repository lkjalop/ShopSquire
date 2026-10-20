"""A payment worker must own both its outbox and downstream ledger database."""
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services import payment_reconcile_scheduler as scheduler
from src.app.services import payment_webhook_delivery as delivery
from src.app.services.payment_ledger import ensure_table


@pytest.fixture
def payment_databases(tmp_path):
    engines = [create_engine('sqlite:///' + str(tmp_path / (name + '.sqlite3')))
               for name in ('owned', 'foreign')]
    for index, engine in enumerate(engines):
        with Session(engine) as db:
            db.execute(text('CREATE TABLE orders (id TEXT PRIMARY KEY, total_cents INTEGER, '
                            'currency TEXT, stripe_intent_id TEXT, status TEXT, updated_at TEXT)'))
            db.execute(text("INSERT INTO orders VALUES (:id,:amount,'AUD','pi_shared','created',NULL)"),
                       {'id': ('owned', 'foreign')[index], 'amount': (100, 200)[index]})
            ensure_table(db)
            delivery.ensure_tables(db)
            delivery.enqueue_job(db, event_id='owned-test-event', job_type='ledger_payment_failed',
                                 payload={'intent_id': 'pi_shared'})
            db.commit()
    yield engines
    for engine in engines:
        engine.dispose()


def test_worker_and_real_ledger_handler_stay_in_the_app_database(payment_databases, monkeypatch):
    from src.app.models import db as database

    owned, foreign = payment_databases
    monkeypatch.setattr(database, 'engine', foreign)
    monkeypatch.setenv('PAYMENT_RECONCILE_SCHEDULER_ENABLED', '1')
    app = SimpleNamespace(state=SimpleNamespace(engine=owned))
    completed = Event()
    real_run = scheduler.run_once

    def observe(*args, **kwargs):
        try:
            return real_run(*args, **kwargs)
        finally:
            completed.set()

    monkeypatch.setattr(scheduler, 'run_once', observe)
    try:
        scheduler.start_payment_reconcile_scheduler(app)
        assert completed.wait(3), 'Owned reconciliation did not complete'
        scheduler.stop_payment_reconcile_scheduler(app)
        with Session(owned) as db:
            assert db.scalar(text('SELECT state FROM payment_side_effect_jobs')) == 'processed'
            assert list(db.execute(text('SELECT order_id,amount_cents,kind FROM payment_transactions'))) == [
                ('owned', 100, 'payment_failed')]
        with Session(foreign) as db:
            assert db.scalar(text('SELECT state FROM payment_side_effect_jobs')) == 'pending'
            assert db.scalar(text('SELECT COUNT(*) FROM payment_transactions')) == 0
        assert not app.state.payment_reconcile_scheduler_thread.is_alive()
    finally:
        scheduler.stop_payment_reconcile_scheduler(app)


@pytest.mark.parametrize('owner', [None, object()])
def test_enabled_payment_worker_requires_database_owner(monkeypatch, owner):
    monkeypatch.setenv('PAYMENT_RECONCILE_SCHEDULER_ENABLED', '1')
    app = SimpleNamespace(state=SimpleNamespace(engine=owner))
    try:
        with pytest.raises(RuntimeError, match='database owner'):
            scheduler.start_payment_reconcile_scheduler(app)
    finally:
        scheduler.stop_payment_reconcile_scheduler(app)


def test_payment_shutdown_retains_in_flight_worker_ownership():
    class InFlightThread:
        def join(self, timeout):
            assert timeout == 5

        def is_alive(self):
            return True

    stop = Event()
    app = SimpleNamespace(state=SimpleNamespace(payment_reconcile_scheduler_stop=stop,
                                               payment_reconcile_scheduler_thread=InFlightThread()))
    with pytest.raises(RuntimeError, match='did not stop'):
        scheduler.stop_payment_reconcile_scheduler(app)
    assert stop.is_set()


def test_disabled_payment_worker_allocates_no_owner_or_thread(monkeypatch):
    monkeypatch.setenv('PAYMENT_RECONCILE_SCHEDULER_ENABLED', '0')
    assert scheduler.start_payment_reconcile_scheduler() is None
