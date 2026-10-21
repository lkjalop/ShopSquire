import pytest
from sqlalchemy import text
from tests.services.test_supplier_enquiry_journey import db, approved, NOW, FakeTransport
from src.app.services import supplier_enquiry_journey as journey
from src.app.services.fulfillment import operator_recovery, outbound_queue


def test_revoke_blocks_dispatch_and_replacement_requires_fresh_independent_approval(db):
    from src.app.services import supplier_enquiry_recovery as recovery
    row=approved(db)
    recovery.revoke(db,tenant_id='shop',enquiry_id=row['id'],operator_principal='alice-key-1',now=NOW)
    with pytest.raises(ValueError,match='not_current'):
        journey.dispatch(db,tenant_id='shop',enquiry_id=row['id'],transport=FakeTransport(),now=NOW)
    replacement=recovery.renew(db,tenant_id='shop',enquiry_id=row['id'],operator_principal='alice-key-1',
        expected_revision=2,reference='replacement-1',recipient_resolver=lambda _:'quotes@fixture.invalid',now=NOW)
    assert replacement['id']!=row['id'] and replacement['status']=='pending'
    assert replacement['source_reference'].startswith('renew:'+row['id']+':')
    with pytest.raises(ValueError,match='approved_enquiry'):
        journey.dispatch(db,tenant_id='shop',enquiry_id=replacement['id'],transport=FakeTransport(),now=NOW)
    journey.approve(db,tenant_id='shop',enquiry_id=replacement['id'],approver_principal='bob-key',now=NOW)
    tx=FakeTransport()
    journey.dispatch(db,tenant_id='shop',enquiry_id=replacement['id'],transport=tx,now=NOW)
    assert tx.calls==1


def test_replacement_reference_cannot_create_second_replacement(db):
    from src.app.services import supplier_enquiry_recovery as recovery
    row=approved(db)
    recovery.revoke(db,tenant_id='shop',enquiry_id=row['id'],operator_principal='alice-key-1',now=NOW)
    args=dict(tenant_id='shop',enquiry_id=row['id'],operator_principal='alice-key-1',expected_revision=2,
        recipient_resolver=lambda _:'quotes@fixture.invalid',now=NOW)
    first=recovery.renew(db,reference='one',**args)
    assert recovery.renew(db,reference='one',**args)['id']==first['id']
    with pytest.raises(ValueError,match='replacement_already_exists'):
        recovery.renew(db,reference='two',**args)


def test_uncertain_effect_requires_reconciliation_before_replacement(db):
    from src.app.services import supplier_enquiry_recovery as recovery
    from src.app.services.fulfillment.transport import SendResult
    class Uncertain:
        calls=0
        def send(self,**_):
            self.calls+=1
            return SendResult(status='unknown',provider_ref='',detail='simulated lost provider response')
    row=approved(db);operator_recovery.ensure_tables(db);tx=Uncertain()
    journey.dispatch(db,tenant_id='shop',enquiry_id=row['id'],transport=tx,now=NOW)
    args=dict(tenant_id='shop',enquiry_id=row['id'],operator_principal='alice-key-1',expected_revision=2,
        reference='replacement-2',recipient_resolver=lambda _:'quotes@fixture.invalid',now=NOW)
    with pytest.raises(ValueError,match='reconciliation_required'):recovery.renew(db,**args)
    recovery.reconcile(db,tenant_id='shop',enquiry_id=row['id'],operator_principal='bob-key',
        outcome='not_delivered',evidence_ref='simulation:provider-ledger:1',provider_ref='',now=NOW)
    replacement=recovery.renew(db,**args)
    assert replacement['status']=='pending'
    assert recovery.renew(db,**args)['id']==replacement['id']
    assert db.execute(text('SELECT COUNT(*) FROM outbound_recovery_observation')).scalar()==1
    outbound_queue.process_pending(db,tenant_id='shop',transport=tx,now_iso=NOW.isoformat())
    assert tx.calls==1


def test_submitted_message_cannot_be_renewed_into_duplicate_send(db):
    from src.app.services import supplier_enquiry_recovery as recovery
    row=approved(db)
    journey.dispatch(db,tenant_id='shop',enquiry_id=row['id'],transport=FakeTransport(),now=NOW)
    with pytest.raises(ValueError,match='replacement_not_safe'):
        recovery.renew(db,tenant_id='shop',enquiry_id=row['id'],operator_principal='alice-key-1',expected_revision=2,
            reference='unsafe-replacement',recipient_resolver=lambda _:'quotes@fixture.invalid',now=NOW)
