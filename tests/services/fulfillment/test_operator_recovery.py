import pytest
from sqlalchemy import text
from tests.services.fulfillment.test_person_approval import db, grant, enqueue, NOW, FakeTransport
from src.app.services.fulfillment import outbound_queue as queue
from src.app.services.fulfillment import operator_recovery as recovery


def prepare(db):
    recovery.ensure_tables(db)
    message = enqueue(db, grant(db))['message_id']
    db.execute(text("UPDATE outbound_message SET status='reconciliation_required' WHERE id=:id"), {'id':message})
    db.commit()
    return message


@pytest.mark.parametrize('outcome,status', [('submitted','sent'), ('not_delivered','resolved_not_delivered')])
def test_recovery_records_observation_without_resending_or_claiming_ack(db,outcome,status):
    message=prepare(db)
    args=dict(tenant_id='shop',message_id=message,operator_principal='bob-key',
              outcome=outcome,evidence_ref='simulation:provider-log:1',
              provider_ref='PROVIDER-1' if outcome=='submitted' else '',now=NOW)
    recovery.resolve(db,**args)
    db.commit()
    recovery.resolve(db,**args)
    db.commit()
    assert db.execute(text('SELECT COUNT(*) FROM outbound_recovery_observation')).scalar()==1
    tx=FakeTransport()
    queue.process_pending(db,tenant_id='shop',transport=tx,now_iso=NOW.isoformat())
    assert tx.calls==0
    row=queue.get_by_key(db,tenant_id='shop',idempotency_key='enquiry-1')
    assert row['status']==status
    assert row['completion_status']!='acknowledged'


@pytest.mark.parametrize('change', ['tenant','operator','evidence','provider','state'])
def test_recovery_requires_scoped_operator_and_observed_outcome(db,change):
    message=prepare(db)
    args=dict(tenant_id='shop',message_id=message,operator_principal='bob-key',outcome='submitted',
              evidence_ref='simulation:provider-log:1',provider_ref='PROVIDER-1',now=NOW)
    if change=='tenant':args['tenant_id']='elsewhere'
    if change=='operator':args['operator_principal']='unknown'
    if change=='evidence':args['evidence_ref']=''
    if change=='provider':args['provider_ref']=''
    if change=='state':db.execute(text("UPDATE outbound_message SET status='pending'"))
    with pytest.raises(ValueError):recovery.resolve(db,**args)
    assert db.execute(text('SELECT COUNT(*) FROM outbound_recovery_observation')).scalar()==0


def test_recovery_rollback_restores_uncertainty_and_conflicting_replay_is_rejected(db):
    message = prepare(db)
    args = dict(tenant_id='shop', message_id=message, operator_principal='bob-key',
                outcome='not_delivered', evidence_ref='simulation:provider-log:1', now=NOW)
    recovery.resolve(db, **args)
    db.rollback()
    assert db.execute(text('SELECT status FROM outbound_message WHERE id=:id'), {'id':message}).scalar() == 'reconciliation_required'
    assert db.execute(text('SELECT COUNT(*) FROM outbound_recovery_observation')).scalar() == 0
    recovery.resolve(db, **args)
    db.commit()
    with pytest.raises(ValueError, match='recovery_observation_conflict'):
        recovery.resolve(db, **{**args, 'outcome':'submitted', 'provider_ref':'PROVIDER-LATE'})


def test_sqlite_recovery_serializes_writer_before_read_snapshot(db, tmp_path):
    """A dashboard write between recovery's read and update must not produce BUSY_SNAPSHOT."""
    import sqlite3
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    message = prepare(db)
    target = tmp_path / 'recovery-race.sqlite'
    with sqlite3.connect(target) as destination:
        db.connection().connection.driver_connection.backup(destination)
    db.rollback()
    engine = create_engine('sqlite:///'+target.as_posix(), connect_args={'timeout': 3})
    with engine.begin() as connection:
        connection.exec_driver_sql('PRAGMA journal_mode=WAL')
        connection.exec_driver_sql('CREATE TABLE race_marker(value INTEGER)')
        connection.exec_driver_sql('INSERT INTO race_marker VALUES (0)')
    trigger, finished = threading.Event(), threading.Event()
    def unrelated_writer():
        assert trigger.wait(3)
        with engine.begin() as connection:
            connection.exec_driver_sql('UPDATE race_marker SET value=1')
        finished.set()
    def after_read(connection, cursor, statement, parameters, context, many):
        if statement.startswith('SELECT payload_digest FROM outbound_recovery_observation'):
            trigger.set()
            finished.wait(0.2)
    event.listen(engine, 'after_cursor_execute', after_read)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            writer = pool.submit(unrelated_writer)
            with Session(engine) as session:
                recovery.resolve(session, tenant_id='shop', message_id=message,
                    operator_principal='bob-key', outcome='not_delivered',
                    evidence_ref='simulation:concurrent-recovery', now=NOW)
                session.commit()
            writer.result(timeout=3)
        with engine.connect() as connection:
            assert connection.execute(text('SELECT COUNT(*) FROM outbound_recovery_observation')).scalar_one() == 1
            assert connection.execute(text('SELECT value FROM race_marker')).scalar_one() == 1
    finally:
        event.remove(engine, 'after_cursor_execute', after_read)
        engine.dispose()
