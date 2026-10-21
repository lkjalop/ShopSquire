"""Real PostgreSQL effect races; fake provider transport never contacts a supplier."""
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.chaos.test_release_integrity_postgres import pg  # noqa: F401


def test_concurrent_purchase_order_dispatch_has_one_provider_effect(pg, monkeypatch):
    from src.app.services.fulfillment import repository as repo, workflow, purchase_order
    from src.app.services.fulfillment.domain import Actor, ActorType
    from src.app.services.fulfillment.po_transport import PoResult
    engine, _, _ = pg
    monkeypatch.setattr(workflow, '_emit_trace', lambda **kwargs: None)
    with engine.begin() as connection:
        for ddl in (*repo._DDL, *repo._INDEXES):
            connection.execute(text(ddl))
    with Session(engine) as db:
        cid = repo.create_case(db, initial_state='PROCUREMENT_APPROVAL_REQUIRED', buyer_uid_hash='buyer',
            source_trace_id=None, requested_by='buyer', tenant_id='a', state_json={
                'purchase_order': {'status':'proposed','quantity':6,'unit_amount_cents':100,'total_amount_cents':600},
                'draft': {'commercial_scope': {'quantity':6}}})
        db.commit()
        human = Actor(ActorType.HUMAN_OPERATOR, 'operator')
        assert workflow.transition(db, case_id=cid, event='purchase_order_approved', actor=human,
            idempotency_key='same-approve', tenant_id='a').ok
    barrier = threading.Barrier(2)
    original = repo.find_idempotent_version
    synchronized = threading.local()
    def synchronized_claim(db, case_id, event, key, tenant_id='default'):
        result = original(db, case_id, event, key, tenant_id)
        # Both workers must observe the absent receipt before either dispatches.
        # Waiting on the new dispatch event would leave older code unraced.
        if event == 'purchase_order_created' and not getattr(synchronized, 'receipt_read', False):
            synchronized.receipt_read = True
            barrier.wait(timeout=10)
        return result
    monkeypatch.setattr(repo, 'find_idempotent_version', synchronized_claim)
    calls = []
    class Provider:
        def create(self, **payload):
            calls.append(payload)
            return PoResult(po_ref='fake-po-1', status='created', detail='sandbox')
    def execute():
        with Session(engine) as db:
            return purchase_order.execute(db, case_id=cid, actor=human, tenant_id='a',
                idempotency_key='same', po_transport=Provider())
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: execute(), range(2)))
    assert len(calls) == 1
    assert sum(result.ok for result in results) == 1
    with Session(engine) as db:
        assert repo.current_version(db, cid, 'a').state == 'READY_TO_SHIP'
        assert db.execute(text('SELECT COUNT(*) FROM fulfillment_case_version WHERE case_id=:id AND valid_to IS NULL'),
                          {'id':cid}).scalar() == 1


def test_refund_permit_revocation_and_unbound_legacy_fail_closed(pg):
    from src.app.services import refund_execution as rx
    engine, _, _ = pg
    with Session(engine) as db:
        eid = rx.open_execution(db, order_id='O1', approval_index=0, amount_cents=None,
                               currency='AUD', intent_id='pi_1', idempotency_key='full-refund')
        assert rx.revoke_pending(db, exec_id=eid, tenant_id='default')
        rx.open_execution(db, order_id='O2', approval_index=0, amount_cents=100,
                          currency='AUD', intent_id='pi_2', idempotency_key='legacy')
        db.execute(text("UPDATE refund_executions SET effect_digest=NULL WHERE order_id='O2'"))
        db.commit()
        calls = []
        assert rx.execute_pending(db, refund_fn=lambda *args: calls.append(args))['settled'] == 0
        assert calls == []


def test_refund_payload_changed_between_read_and_claim_cannot_dispatch(pg, monkeypatch):
    from src.app.services import refund_execution as rx, refund_authorization as auth
    engine, _, _ = pg
    with Session(engine) as db:
        eid = rx.open_execution(db, order_id='O1', approval_index=0, amount_cents=100,
                               currency='AUD', intent_id='pi_1', idempotency_key='race')
        original = auth.refund_permit_current
        def race(row):
            valid = original(row)
            with engine.begin() as other:
                other.execute(text('UPDATE refund_executions SET amount_cents=999 WHERE id=:id'), {'id':eid})
            return valid
        monkeypatch.setattr(auth, 'refund_permit_current', race)
        calls = []
        rx.execute_pending(db, refund_fn=lambda *args: calls.append(args))
        assert calls == []


def test_concurrent_outbound_workers_transmit_once(pg):
    from src.app.services.fulfillment import outbound_queue as queue
    engine, _, _ = pg
    from tests.services.test_communication_lifecycle import _upgrade
    with engine.begin() as connection:
        _upgrade(connection, "20260812_communication_observations.py")
        _upgrade(connection, "20260826_communication_lifecycle.py")
    with Session(engine) as db:
        db.execute(text(queue._DDL))
        db.commit()
        queued = queue.enqueue(db, tenant_id='a', case_id='c1', recipient='supplier@example.invalid',
                               subject='RFQ', body='Request quote', idempotency_key='one-effect')
        assert queued['status'] == 'pending'
    barrier, lock = threading.Barrier(2), threading.Lock()
    sent = []
    class Transport:
        def send(self, **message):
            with lock:
                sent.append(message)
            return SimpleNamespace(status='sent', provider_ref='provider-one', detail='test')
    def worker():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return queue.process_pending(db, tenant_id='a', transport=Transport())
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _:worker(), range(2)))
    assert len(sent) == 1 and sum(r['sent'] for r in results) == 1
    with Session(engine) as db:
        result = queue.get_by_key(db, tenant_id='a', idempotency_key='one-effect')
        assert result['completion_status'] == 'submitted_unverified'


def test_concurrent_refund_completion_is_exact_and_replay_safe(pg):
    from src.app.services import refund_execution as refunds
    engine, _, _ = pg
    with Session(engine) as db:
        ids = [refunds.open_execution(db, order_id='o1', approval_index=i, amount_cents=1000,
                currency='AUD', intent_id='pi_shared', idempotency_key=f'key-{i}') for i in range(2)]
        for i, execution in enumerate(ids):
            refunds.mark_submitted(db, execution, provider_ref=f're_{i}')
    barrier = threading.Barrier(2)
    def settle():
        with Session(engine) as db:
            barrier.wait(timeout=10)
            return refunds.settle_submitted_for_intent(db, intent_id='pi_shared', provider_ref='re_0')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _:settle(), range(2)))
    assert sorted(results) == [0, 1]
    with Session(engine) as db:
        assert db.execute(text('SELECT state FROM refund_executions WHERE id=:i'), {'i':ids[1]}).scalar() == 'provider_submitted'


def test_duplicate_refund_jobs_cannot_double_append_ledger(pg, monkeypatch):
    from contextlib import contextmanager
    from src.app.routers import payments
    from src.app.services import payment_ledger as ledger, refund_execution as refunds
    engine, _, _ = pg
    with Session(engine) as db:
        db.execute(text("CREATE TABLE orders (id TEXT PRIMARY KEY, total_cents INTEGER, currency TEXT, "
                        "stripe_intent_id TEXT, status TEXT, updated_at TIMESTAMP)"))
        db.execute(text("INSERT INTO orders VALUES ('o1',5000,'AUD','pi_concurrent','paid',now())"))
        db.commit()
        ledger.ensure_table(db)
        refunds.ensure_table(db)
        db.commit()
        ledger.record_txn(db, order_id='o1', kind=ledger.KIND_REFUND_APPROVED,
                          intent_id='pi_concurrent', amount_cents=1000, currency='AUD')
    @contextmanager
    def session():
        with Session(engine) as db:
            yield db
    monkeypatch.setattr(payments, 'db_session', session)
    barrier = threading.Barrier(2)
    def drive():
        barrier.wait(timeout=10)
        payments._handle_payment_outbox_job('reconcile_refund',
            {'intent_id':'pi_concurrent','provider_ref':'re_concurrent','amount_cents':1000})
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _:drive(), range(2)))
    with Session(engine) as db:
        assert ledger.refund_state(db, 'o1')['settled_cents'] == 1000
        assert db.execute(text("SELECT status FROM orders WHERE id='o1'")).scalar() == 'paid'
