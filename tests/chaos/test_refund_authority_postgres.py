"""Exact refund effects on a generated, local PostgreSQL certificate schema."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import os
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.fixture
def refund_engine():
    value = os.getenv('TEST_POSTGRES_URL')
    if not value:
        pytest.skip('TEST_POSTGRES_URL is required for isolated refund authority races')
    url = make_url(value)
    assert url.get_backend_name() == 'postgresql'
    assert url.host in {'127.0.0.1', 'localhost'}
    assert (url.database or '').startswith('shopsquire_cert_')
    admin = create_engine(url)
    schema = 'refund_' + uuid4().hex
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={'connect_timeout': 3,
        'options': f'-csearch_path={schema} -cstatement_timeout=10000 -clock_timeout=5000'})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_refund_permit_revocation_and_unbound_legacy_fail_closed(refund_engine):
    from src.app.services import refund_execution as refunds
    with Session(refund_engine) as db:
        revoked = refunds.open_execution(db, order_id='one', approval_index=0, amount_cents=None,
            currency='AUD', intent_id='pi_one', idempotency_key='full-refund')
        assert refunds.revoke_pending(db, exec_id=revoked, tenant_id='default')
        refunds.open_execution(db, order_id='two', approval_index=0, amount_cents=100,
            currency='AUD', intent_id='pi_two', idempotency_key='legacy')
        db.execute(text("UPDATE refund_executions SET effect_digest=NULL WHERE order_id='two'"))
        db.commit()
        calls = []
        assert refunds.execute_pending(db, refund_fn=lambda *args: calls.append(args))['settled'] == 0
        assert calls == []


def test_payload_changed_between_read_and_claim_cannot_dispatch(refund_engine, monkeypatch):
    from src.app.services import refund_execution as refunds, refund_authorization as authority
    with Session(refund_engine) as db:
        execution = refunds.open_execution(db, order_id='one', approval_index=0, amount_cents=100,
            currency='AUD', intent_id='pi_one', idempotency_key='race')
        original = authority.refund_permit_current

        def race(row):
            valid = original(row)
            with refund_engine.begin() as other:
                other.execute(text('UPDATE refund_executions SET amount_cents=999 WHERE id=:id'),
                              {'id': execution})
            return valid

        monkeypatch.setattr(authority, 'refund_permit_current', race)
        calls = []
        refunds.execute_pending(db, refund_fn=lambda *args: calls.append(args))
        assert calls == []


def test_concurrent_completion_settles_only_one_exact_partial_refund(refund_engine):
    from src.app.services import refund_execution as refunds
    with Session(refund_engine) as db:
        executions = [refunds.open_execution(db, order_id='one', approval_index=i,
            amount_cents=1000, currency='AUD', intent_id='pi_shared', idempotency_key=f'key-{i}')
            for i in range(2)]
        for i, execution in enumerate(executions):
            refunds.mark_submitted(db, execution, provider_ref=f're_{i}')
    barrier = Barrier(2)

    def settle():
        with Session(refund_engine) as db:
            barrier.wait(timeout=5)
            return refunds.settle_submitted_for_intent(db, intent_id='pi_shared', provider_ref='re_0')

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: settle(), range(2))) == [0, 1]
    with Session(refund_engine) as db:
        assert db.scalar(text('SELECT state FROM refund_executions WHERE id=:id'),
                         {'id': executions[1]}) == refunds.STATE_SUBMITTED


def test_duplicate_jobs_append_one_partial_refund_without_returning_whole_order(refund_engine, monkeypatch):
    from src.app.routers import payments
    from src.app.services import payment_ledger as ledger, refund_execution as refunds
    with Session(refund_engine) as db:
        db.execute(text('CREATE TABLE orders (id TEXT PRIMARY KEY,total_cents INTEGER,currency TEXT,'
                        'stripe_intent_id TEXT,status TEXT,updated_at TIMESTAMP)'))
        db.execute(text("INSERT INTO orders VALUES ('one',5000,'AUD','pi_shared','paid',now())"))
        ledger.ensure_table(db)
        refunds.ensure_table(db)
        db.commit()
        ledger.record_txn(db, order_id='one', kind=ledger.KIND_REFUND_APPROVED,
                          intent_id='pi_shared', amount_cents=1000, currency='AUD')

    @contextmanager
    def sessions():
        with Session(refund_engine) as db:
            yield db

    monkeypatch.setattr(payments, 'db_session', sessions)
    barrier = Barrier(2)

    def settle():
        barrier.wait(timeout=5)
        payments._handle_payment_outbox_job('reconcile_refund',
            {'intent_id': 'pi_shared', 'provider_ref': 're_same', 'amount_cents': 1000})

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: settle(), range(2)))
    with Session(refund_engine) as db:
        assert ledger.refund_state(db, 'one')['settled_cents'] == 1000
        assert db.scalar(text("SELECT status FROM orders WHERE id='one'")) == 'paid'


def test_stale_provider_result_cannot_overwrite_new_worker(refund_engine):
    from src.app.services import refund_execution as refunds
    with Session(refund_engine) as db:
        execution = refunds.open_execution(db, order_id='one', approval_index=0, amount_cents=100,
            currency='AUD', intent_id='pi_one', idempotency_key='fenced')

        def provider(*args):
            with refund_engine.begin() as newer:
                newer.execute(text("UPDATE refund_executions SET claim_token='new-worker',"
                    "state='settled',provider_ref='re_new' WHERE id=:id"), {'id': execution})
            return {'id': 're_stale', 'status': 'pending'}

        refunds.execute_pending(db, refund_fn=provider)
        assert tuple(db.execute(text('SELECT state,provider_ref FROM refund_executions WHERE id=:id'),
                                {'id': execution}).one()) == ('settled', 're_new')
