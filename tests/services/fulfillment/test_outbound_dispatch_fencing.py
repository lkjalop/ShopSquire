"""A transport result cannot undo a hold imposed while that worker was busy."""
import pytest
from sqlalchemy import text

from tests.services.fulfillment.test_outbound_queue import (
    db, _enq, _Res, _CountingTransport,
)
from src.app.services.fulfillment import outbound_queue as queue


@pytest.mark.parametrize('status', ['sent', 'failed', 'unknown'])
def test_late_transport_result_preserves_reconciliation_hold(db, status):
    _enq(db)

    class LateTransport:
        def send(self, **payload):
            queue._reclaim_stale(db, tenant_id='default', ts='2026-06-28T10:10:00')
            db.commit()
            return _Res(status, provider_ref='provider-receipt')

    result = queue.process_pending(db, transport=LateTransport(), now_iso='2026-06-28T10:00:01')
    row = db.execute(text('SELECT status,provider_ref FROM outbound_message')).first()
    assert row[0] == 'reconciliation_required'
    assert row[1] is None
    assert result['sent'] == result['retried'] == result['dead_lettered'] == 0
    assert result['settlement_conflicts'] == 1


def test_worker_reclaimed_during_scan_does_not_start_transport(db, monkeypatch):
    _enq(db)

    def scan(*args, **kwargs):
        queue._reclaim_stale(db, tenant_id='default', ts='2026-06-28T10:10:00')
        db.commit()
        return {'action': 'allow'}

    monkeypatch.setattr('src.app.services.fulfillment.outbound_integrity.scan_outbound_supplier_message', scan)
    transport = _CountingTransport()
    queue.process_pending(db, transport=transport, now_iso='2026-06-28T10:00:01')
    assert transport.calls == 0
    assert db.execute(text('SELECT status FROM outbound_message')).scalar_one() == 'reconciliation_required'


@pytest.mark.parametrize('scan_result', [None, {}, {'action': 'review'}, {'action': 'unexpected'}])
def test_only_an_explicit_integrity_allow_can_dispatch(db, monkeypatch, scan_result):
    _enq(db)
    monkeypatch.setattr('src.app.services.fulfillment.outbound_integrity.scan_outbound_supplier_message',
                        lambda *args, **kwargs: scan_result)
    transport = _CountingTransport()
    queue.process_pending(db, transport=transport, now_iso='2026-06-28T10:00:01')
    assert transport.calls == 0
    assert db.execute(text('SELECT status FROM outbound_message')).scalar_one() == 'blocked_content'


@pytest.mark.parametrize('clock', ['2026-06-28T12:00:01+02:00', '2026-06-28T03:00:01-07:00'])
def test_equivalent_worker_clocks_cannot_delay_or_expire_a_valid_message(db, clock):
    _enq(db, now='2026-06-28T10:00:00+00:00')
    transport = _CountingTransport()
    queue.process_pending(db, transport=transport, now_iso=clock)
    assert transport.calls == 1


def test_contact_window_offset_cannot_make_a_future_message_due(db):
    queue.enqueue(db, case_id='c1', recipient='s@fixture.invalid', subject='RFQ', body='request',
        idempotency_key='window', now_iso='2026-06-28T09:00:00+00:00',
        response_expectation={'transmission_state': 'queue_until_open',
                              'next_open_at': '2026-06-28T04:00:00-07:00'})
    transport = _CountingTransport()
    queue.process_pending(db, transport=transport, now_iso='2026-06-28T10:00:00+00:00')
    assert transport.calls == 0


def test_existing_offset_window_cannot_make_a_future_message_due(db):
    _enq(db)
    db.execute(text("UPDATE outbound_message SET next_attempt_at='2026-06-28T04:00:00-07:00'"))
    db.commit()
    transport = _CountingTransport()
    queue.process_pending(db, transport=transport, now_iso='2026-06-28T10:00:00+00:00')
    assert transport.calls == 0


def test_existing_offset_claim_is_not_stale_when_its_utc_age_is_one_minute(db):
    _enq(db)
    db.execute(text("UPDATE outbound_message SET status='sending',updated_at='2026-06-28T03:59:00-06:00'"))
    db.commit()
    queue.process_pending(db, transport=_CountingTransport(), now_iso='2026-06-28T10:00:00+00:00')
    assert db.execute(text('SELECT status FROM outbound_message')).scalar_one() == 'sending'
