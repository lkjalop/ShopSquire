"""Concurrent outbound attempts on an owned PostgreSQL schema, with fake effects."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, Lock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from src.app.services.fulfillment import outbound_queue as queue
from src.app.services.fulfillment.transport import SendResult
from tests.migration_helpers import apply_revision


@pytest.fixture
def outbound_engine(monkeypatch):
    value = os.getenv('TEST_POSTGRES_URL')
    if not value:
        pytest.skip('TEST_POSTGRES_URL is required for isolated outbound races')
    url = make_url(value)
    assert url.get_backend_name() == 'postgresql'
    assert url.host in {'127.0.0.1', 'localhost'}
    assert (url.database or '').startswith('shopsquire_cert_')
    admin = create_engine(url)
    schema = 'outbound_' + uuid4().hex
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={'connect_timeout': 3,
        'options': f'-csearch_path={schema} -cstatement_timeout=10000 -clock_timeout=5000 -ctimezone=Pacific/Auckland'})
    try:
        apply_revision(engine, '20260812_communication_observations.py')
        apply_revision(engine, '20260826_communication_lifecycle.py')
        with Session(engine) as db:
            db.execute(text(queue._DDL))
            db.commit()
        monkeypatch.setattr('src.app.services.fulfillment.outbound_integrity.scan_outbound_supplier_message',
                            lambda *args, **kwargs: {'action': 'allow'})
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def enqueue(engine):
    with Session(engine) as db:
        result = queue.enqueue(db, tenant_id='shop', case_id='case', recipient='supplier@fixture.invalid',
            subject='Enquiry', body='Please quote 15 units', idempotency_key='one', now_iso='2026-06-28T10:00:00')
        assert result['message_id']


@pytest.mark.parametrize('status', ['sent', 'failed', 'unknown'])
def test_late_receipt_cannot_remove_another_session_reconciliation_hold(outbound_engine, status):
    enqueue(outbound_engine)

    class LateTransport:
        def send(self, **payload):
            with Session(outbound_engine) as other:
                queue._reclaim_stale(other, tenant_id='shop', ts='2026-06-28T10:10:00')
                other.commit()
            return SendResult(status=status, provider_ref='provider-one')

    with Session(outbound_engine) as db:
        result = queue.process_pending(db, tenant_id='shop', transport=LateTransport(), now_iso='2026-06-28T10:00:01')
        assert result['settlement_conflicts'] == 1
    with outbound_engine.connect() as db:
        row = db.execute(text('SELECT status,provider_ref FROM outbound_message')).one()
        assert tuple(row) == ('reconciliation_required', None)
        assert db.scalar(text("SELECT COUNT(*) FROM communication_lifecycle_event WHERE state='submitted'")) == 0


def test_two_workers_observing_the_same_pending_message_only_send_once(outbound_engine, monkeypatch):
    enqueue(outbound_engine)
    barrier, mutex = Barrier(2), Lock()
    calls = []
    from src.app.services.fulfillment import person_approval
    original = person_approval.dispatch_current

    def synchronize(db, tenant, approval_id, digest, now):
        if not db.info.get('observed_pending'):
            db.info['observed_pending'] = True
            barrier.wait(timeout=5)
        return original(db, tenant, approval_id, digest, now)

    monkeypatch.setattr(person_approval, 'dispatch_current', synchronize)

    class Transport:
        def send(self, **payload):
            with mutex:
                calls.append(payload)
            return SendResult(status='sent', provider_ref='provider-one')

    def work(_):
        with Session(outbound_engine) as db:
            return queue.process_pending(db, tenant_id='shop', transport=Transport(), now_iso='2026-06-28T10:00:01')

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(work, range(2)))
    assert len(calls) == sum(row['sent'] for row in results) == 1
    with outbound_engine.connect() as db:
        assert tuple(db.execute(text('SELECT status,attempts FROM outbound_message')).one()) == ('sent', 1)
        assert db.scalar(text("SELECT COUNT(*) FROM communication_lifecycle_event WHERE state='submitted'")) == 1


def test_payload_changed_after_validation_cannot_be_claimed(outbound_engine, monkeypatch):
    enqueue(outbound_engine)
    from src.app.services.fulfillment import person_approval
    original = person_approval.dispatch_current

    def change(db, tenant, approval_id, digest, now):
        with outbound_engine.begin() as other:
            other.execute(text("UPDATE outbound_message SET body='Please quote 40 units'"))
        return original(db, tenant, approval_id, digest, now)

    monkeypatch.setattr(person_approval, 'dispatch_current', change)
    calls = []

    class Transport:
        def send(self, **payload):
            calls.append(payload)
            return SendResult(status='sent', provider_ref='provider-one')

    with Session(outbound_engine) as db:
        assert queue.process_pending(db, tenant_id='shop', transport=Transport(),
                                     now_iso='2026-06-28T10:00:01')['processed'] == 0
    assert calls == []


def test_legacy_offset_clocks_remain_safe_on_a_non_utc_database(outbound_engine):
    enqueue(outbound_engine)
    with outbound_engine.begin() as db:
        db.execute(text("UPDATE outbound_message SET next_attempt_at='2026-06-28T04:00:00-07:00'"))
    calls = []

    class Transport:
        def send(self, **payload):
            calls.append(payload)
            return SendResult(status='sent', provider_ref='provider-one')

    with Session(outbound_engine) as db:
        queue.process_pending(db, tenant_id='shop', transport=Transport(), now_iso='2026-06-28T10:00:00Z')
        assert db.scalar(text('SELECT status FROM outbound_message')) == 'pending'
    with outbound_engine.begin() as db:
        db.execute(text("UPDATE outbound_message SET status='sending',updated_at='2026-06-28T03:59:00-06:00'"))
    with Session(outbound_engine) as db:
        queue.process_pending(db, tenant_id='shop', transport=Transport(), now_iso='2026-06-28T10:00:00Z')
        assert db.scalar(text('SELECT status FROM outbound_message')) == 'sending'
    assert calls == []
