from datetime import datetime,timezone,timedelta
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from src.app.services.fulfillment import outbound_queue as queue
from src.app.services.fulfillment import person_approval as approval

NOW=datetime(2026,9,27,tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:')
    with Session(engine) as db:
        db.execute(text(queue._DDL))
        approval.ensure_tables(db)
        db.execute(text('CREATE TABLE operator_tenant_membership (tenant_id TEXT,principal_hash TEXT,role TEXT,status TEXT)'))
        for credential,person in [('alice-key-1','alice'),('alice-key-2','alice'),('bob-key','bob')]:
            db.execute(text("INSERT INTO operator_tenant_membership VALUES ('shop',:credential,'owner','active')"),{'credential':credential})
            approval.bind_person(db,tenant_id='shop',principal_hash=credential,person_id=person,assigned_by='fixture-admin')
        db.commit()
        yield db
    engine.dispose()


def payload(approver='bob-key'):
    return dict(tenant_id='shop',case_id='case',recipient='supplier@fixture.invalid',subject='Enquiry',body='Quote 30 units',
        channel='email',actor_type='human_operator',actor_id=approver,transition_event='external_message_sent',idempotency_key='enquiry-1')


def grant(db,approver='bob-key',value=3000000):
    return approval.issue(db,requester_principal='alice-key-1',approver_principal=approver,
        effect=payload(approver),value_cents=value,expires_at=NOW+timedelta(hours=1),now=NOW)


@pytest.mark.parametrize('approver',['alice-key-1','alice-key-2'])
def test_one_person_cannot_self_approve_with_another_credential(db,approver):
    with pytest.raises(ValueError,match='distinct_people'):grant(db,approver)


def test_required_spend_tier_is_enforced(db):
    db.execute(text("UPDATE operator_tenant_membership SET role='manager' WHERE principal_hash='bob-key'"))
    with pytest.raises(ValueError,match='tier'):grant(db,value=3000000)


def enqueue(db,receipt):
    return queue.enqueue(db,**payload(),person_approval_id=receipt['id'],now_iso=NOW.isoformat())


class FakeTransport:
    calls=0
    def send(self,**kwargs):
        from src.app.services.fulfillment.transport import SendResult
        self.calls+=1
        return SendResult(provider_ref='DEMO-OUT-proof',status='sent')


def test_two_people_can_approve_exact_simulated_effect_and_replay_is_safe(db):
    receipt=grant(db)
    assert enqueue(db,receipt)['message_id']
    tx=FakeTransport()
    queue.process_pending(db,tenant_id='shop',transport=tx,now_iso=NOW.isoformat())
    queue.process_pending(db,tenant_id='shop',transport=tx,now_iso=NOW.isoformat())
    assert tx.calls==1


@pytest.mark.parametrize('change',['revocation','membership','person_mapping','bytes','strip_grant','expiry'])
def test_authority_is_revalidated_at_dispatch(db,change):
    receipt=grant(db)
    enqueue(db,receipt)
    if change=='revocation':approval.revoke(db,tenant_id='shop',approval_id=receipt['id'],revoked_by='admin',now=NOW)
    if change=='membership':db.execute(text("UPDATE operator_tenant_membership SET status='revoked' WHERE principal_hash='bob-key'"))
    if change=='person_mapping':db.execute(text("UPDATE operator_person_binding SET person_id='alice' WHERE principal_hash='bob-key'"))
    if change=='bytes':db.execute(text("UPDATE outbound_message SET body='Quote 40 units'"))
    if change=='strip_grant':db.execute(text('UPDATE outbound_message SET person_approval_id=NULL'))
    db.commit()
    tx=FakeTransport()
    now=NOW+timedelta(hours=2) if change=='expiry' else NOW
    queue.process_pending(db,tenant_id='shop',transport=tx,now_iso=now.isoformat())
    assert tx.calls==0
    assert queue.get_by_key(db,tenant_id='shop',idempotency_key='enquiry-1')['status']=='blocked_authority'


def test_approval_expiring_during_integrity_scan_is_not_dispatched(db, monkeypatch):
    receipt = grant(db)
    enqueue(db, receipt)
    clock = [0.0]
    monkeypatch.setattr(queue, 'monotonic', lambda: clock[0], raising=False)
    def slow_scan(*args, **kwargs):
        clock[0] = 3601.0
        return {'action': 'allow'}
    monkeypatch.setattr('src.app.services.fulfillment.outbound_integrity.scan_outbound_supplier_message', slow_scan)
    tx = FakeTransport()
    queue.process_pending(db, tenant_id='shop', transport=tx, now_iso=NOW.isoformat())
    assert tx.calls == 0
