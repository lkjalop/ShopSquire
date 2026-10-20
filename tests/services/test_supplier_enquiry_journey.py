from datetime import timedelta
import json
import pytest
from sqlalchemy import text
from tests.services.fulfillment.test_person_approval import db, NOW, FakeTransport
from src.app.services import supplier_enquiry_journey as journey
from src.app.services.fulfillment import person_approval as approval


def prepare(db):
    from tests.migration_helpers import apply_revision
    apply_revision(db.get_bind(), '20260853_conversation_case_state.py')
    journey.ensure_tables(db)
    db.execute(text('CREATE TABLE shopping_cases(case_id TEXT,tenant_id TEXT,revision INTEGER)'))
    db.execute(text("INSERT INTO shopping_cases VALUES ('case','shop',2)"))
    db.execute(text('CREATE TABLE shopping_case_fulfillment_selections(selection_id TEXT,case_id TEXT,tenant_id TEXT,revision INTEGER,preferred_sku TEXT,requested_quantity INTEGER)'))
    db.execute(text("INSERT INTO shopping_case_fulfillment_selections VALUES ('sel','case','shop',2,'SKU',30)"))
    db.execute(text('CREATE TABLE inventory_reservation(tenant_id TEXT,reservation_id TEXT,quantity INTEGER,status TEXT,expires_at TEXT)'))
    db.execute(text("INSERT INTO inventory_reservation VALUES ('shop','selection:sel:warehouse',15,'reserved',:expiry)"),{'expiry':(NOW+timedelta(hours=2)).isoformat()})
    db.execute(text('CREATE TABLE products(sku TEXT,price_cents INTEGER,currency TEXT,active BOOLEAN DEFAULT 1)'))
    db.execute(text("INSERT INTO products(sku,price_cents,currency) VALUES ('SKU',100000,'AUD')"))
    db.commit()


def create(db):
    return journey.create(db,tenant_id='shop',case_id='case',expected_revision=2,
        requester_principal='alice-key-1',supplier_ref='fictional-distributor',source_reference='rfq1',
        recipient_resolver=lambda ref:'quotes@fixture.invalid',now=NOW)


def approved(db):
    prepare(db);row=create(db)
    return journey.approve(db,tenant_id='shop',enquiry_id=row['id'],approver_principal='bob-key',now=NOW)


def quote(**changes):
    return dict(sku='SKU',quantity=15,unit_cost_cents=70000,freight_cents=12000,
        currency='AUD',lead_days=5,minimum_order=1,expires_at=(NOW+timedelta(days=1)).isoformat(),**changes)


def sent(db):
    row=approved(db);tx=FakeTransport()
    journey.dispatch(db,tenant_id='shop',enquiry_id=row['id'],transport=tx,now=NOW)
    return row,tx


def test_approved_shortfall_send_is_exact_and_replay_safe(db):
    prepare(db);row=create(db)
    assert row['shortfall']==15 and row['value_cents']==3000000
    with pytest.raises(ValueError,match='approved'):
        journey.dispatch(db,tenant_id='shop',enquiry_id=row['id'],transport=FakeTransport(),now=NOW)
    for actor in ['alice-key-1','alice-key-2']:
        with pytest.raises(ValueError,match='distinct_people'):
            journey.approve(db,tenant_id='shop',enquiry_id=row['id'],approver_principal=actor,now=NOW)
    row=journey.approve(db,tenant_id='shop',enquiry_id=row['id'],approver_principal='bob-key',now=NOW)
    tx=FakeTransport()
    for _ in range(2):journey.dispatch(db,tenant_id='shop',enquiry_id=row['id'],transport=tx,now=NOW)
    assert tx.calls==1
    view=journey.view(db,tenant_id='shop',enquiry_id=row['id'],now=NOW)
    assert view['delivery_status']=='sent' and view['reply_status']=='awaiting_reply'
    assert view['commerce_authority']=='none'
    assert view['message'] == {
        'recipient':'quotes@fixture.invalid', 'subject':'Stock shortfall enquiry',
        'body':'Please quote 15 units of SKU for case revision 2. No purchase is authorized.'}


@pytest.mark.parametrize('change',['revision','revocation','membership','expiry'])
def test_changed_authority_never_sends(db,change):
    row=approved(db)
    if change=='revision':db.execute(text('UPDATE shopping_cases SET revision=3'))
    if change=='revocation':approval.revoke(db,tenant_id='shop',approval_id=row['approval_id'],revoked_by='bob-key',now=NOW)
    if change=='membership':db.execute(text("UPDATE operator_tenant_membership SET status='revoked' WHERE principal_hash='bob-key'"))
    tx=FakeTransport()
    with pytest.raises(ValueError):journey.dispatch(db,tenant_id='shop',enquiry_id=row['id'],transport=tx,now=NOW+timedelta(hours=2) if change=='expiry' else NOW)
    assert tx.calls==0


def test_reply_requires_current_scope_sender_and_explicit_review(db):
    row,tx=sent(db)
    reply=journey.receive(db,tenant_id='shop',enquiry_id=row['id'],message_id='reply1',sender_ref='fictional-distributor',terms=quote(),now=NOW)
    assert reply['status']=='review_required'
    assert journey.receive(db,tenant_id='shop',enquiry_id=row['id'],message_id='reply1',sender_ref='fictional-distributor',terms=quote(),now=NOW)['id']==reply['id']
    changed=quote();changed['unit_cost_cents']=1
    with pytest.raises(ValueError,match='conflict'):journey.receive(db,tenant_id='shop',enquiry_id=row['id'],message_id='reply1',sender_ref='fictional-distributor',terms=changed,now=NOW)
    reviewed=journey.review(db,tenant_id='shop',enquiry_id=row['id'],reply_id=reply['id'],reviewer_principal='bob-key',now=NOW)
    assert reviewed['status']=='reviewed'
    view=journey.view(db,tenant_id='shop',enquiry_id=row['id'],now=NOW)
    assert view['quotes'][0]['assessment']['landed_cost_cents']==1062000
    assert view['quotes'][0]['assessment']['coverage']=='full'
    assert tx.calls==1


def test_case_amendment_blocks_already_queued_enquiry_at_worker_dispatch(db):
    from src.app.services.fulfillment import outbound_queue as queue
    row=approved(db)
    queue.enqueue(db,**journey._effect(row,'bob-key'),person_approval_id=row['approval_id'],now_iso=NOW.isoformat())
    db.execute(text('UPDATE shopping_cases SET revision=3'));db.commit()
    tx=FakeTransport()
    queue.process_pending(db,tenant_id='shop',transport=tx,now_iso=NOW.isoformat())
    assert tx.calls==0
    assert queue.get_by_key(db,tenant_id='shop',idempotency_key='supplier-enquiry:'+row['id'])['status']=='blocked_authority'


def test_immediate_dispatch_preserves_subsecond_approval_time(db):
    prepare(db);row=create(db)
    issued=NOW+timedelta(microseconds=700000)
    journey.approve(db,tenant_id='shop',enquiry_id=row['id'],approver_principal='bob-key',now=issued)
    tx=FakeTransport()
    result=journey.dispatch(db,tenant_id='shop',enquiry_id=row['id'],transport=tx,now=issued+timedelta(microseconds=1000))
    assert result['delivery_status']=='sent'
    assert tx.calls==1


@pytest.mark.parametrize('queued', [False, True])
def test_expired_inventory_invalidates_enquiry_at_actual_dispatch(db, queued):
    from src.app.services.fulfillment import outbound_queue as queue
    row=approved(db)
    if queued:
        queue.enqueue(db,**journey._effect(row,'bob-key'),person_approval_id=row['approval_id'],now_iso=NOW.isoformat())
    db.execute(text("UPDATE inventory_reservation SET status='expired'"));db.commit()
    transport=FakeTransport()
    if queued:
        queue.process_pending(db,tenant_id='shop',transport=transport,now_iso=NOW.isoformat())
        assert queue.get_by_key(db,tenant_id='shop',idempotency_key='supplier-enquiry:'+row['id'])['status']=='blocked_authority'
    else:
        with pytest.raises(ValueError,match='shortfall_stale'):
            journey.dispatch(db,tenant_id='shop',enquiry_id=row['id'],transport=transport,now=NOW)
    assert transport.calls==0


@pytest.mark.parametrize('status,remaining', [('shipped',15),('returned',15),('cancelled',30),('expired',30)])
def test_shortfall_respects_fulfillment_lifecycle(db,status,remaining):
    prepare(db)
    db.execute(text('UPDATE inventory_reservation SET status=:status'),{'status':status})
    assert create(db)['shortfall']==remaining


def test_actual_sourced_quantity_must_meet_minimum(db):
    row,_=sent(db)
    terms=quote();terms.update(quantity=4,minimum_order=10)
    reply=journey.receive(db,tenant_id='shop',enquiry_id=row['id'],message_id='moq',sender_ref='fictional-distributor',terms=terms,now=NOW)
    journey.review(db,tenant_id='shop',enquiry_id=row['id'],reply_id=reply['id'],reviewer_principal='bob-key',now=NOW)
    assessment=journey.view(db,tenant_id='shop',enquiry_id=row['id'],now=NOW)['quotes'][0]['assessment']
    assert assessment['coverage']=='below_minimum'
    assert assessment['eligible'] is False
    assert assessment['landed_cost_cents'] is None


def test_previously_reviewed_reply_loses_eligibility_when_hold_expires(db):
    row,_=sent(db)
    reply=journey.receive(db,tenant_id='shop',enquiry_id=row['id'],message_id='current',sender_ref='fictional-distributor',terms=quote(),now=NOW)
    journey.review(db,tenant_id='shop',enquiry_id=row['id'],reply_id=reply['id'],reviewer_principal='bob-key',now=NOW)
    db.execute(text("UPDATE inventory_reservation SET status='expired'"))
    current=journey.view(db,tenant_id='shop',enquiry_id=row['id'],now=NOW)['quotes'][0]
    assert current['reason']=='stale_shortfall'
    assert current['assessment']['eligible'] is False
    assert current['assessment']['landed_cost_cents'] is None


@pytest.mark.parametrize('variant',['wrong_sender','expired','substitute','partial','stale'])
def test_unusable_and_conditional_replies_do_not_become_full_quotes(db,variant):
    row,_=sent(db);terms=quote();sender='fictional-distributor'
    if variant=='wrong_sender':sender='attacker'
    if variant=='expired':terms['expires_at']=(NOW-timedelta(seconds=1)).isoformat()
    if variant=='substitute':terms['sku']='OTHER'
    if variant=='partial':terms['quantity']=4
    if variant=='stale':db.execute(text('UPDATE shopping_cases SET revision=3'))
    reply=journey.receive(db,tenant_id='shop',enquiry_id=row['id'],message_id=variant,sender_ref=sender,terms=terms,now=NOW)
    if variant in ('wrong_sender','expired','stale'):
        assert reply['status']=='quarantined'
        with pytest.raises(ValueError):journey.review(db,tenant_id='shop',enquiry_id=row['id'],reply_id=reply['id'],reviewer_principal='bob-key',now=NOW)
    else:
        journey.review(db,tenant_id='shop',enquiry_id=row['id'],reply_id=reply['id'],reviewer_principal='bob-key',now=NOW)
        assessment=journey.view(db,tenant_id='shop',enquiry_id=row['id'],now=NOW)['quotes'][0]['assessment']
        assert assessment['coverage']==('substitute_unverified' if variant=='substitute' else 'partial')
