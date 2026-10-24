from datetime import timedelta
import pytest
from sqlalchemy import text
from tests.services.fulfillment.test_person_approval import db, NOW
from src.app.services import operator_inventory_requests as requests
from src.app.services.fulfillment import person_approval
from src.app.services.inventory_transactions import ensure_tables
from src.app.services.commerce_catalog import upsert_inventory


def prepare(db):
    ensure_tables(db)
    db.execute(text(requests.REQUEST_DDL))
    db.execute(text('CREATE TABLE products(sku TEXT PRIMARY KEY,price_cents INTEGER,currency TEXT)'))
    db.execute(text("INSERT INTO products VALUES ('SKU',100000,'AUD')"))
    upsert_inventory(db,tenant_id='shop',sku='SKU',location_id='warehouse',on_hand=5,reserved=0)
    db.commit()


def request(db):
    return requests.create_request(db,tenant_id='shop',requester_principal='alice-key-1',
        kind='receive',sku='SKU',destination_location='warehouse',source_reference='delivery:1',quantity=3)


def test_two_authenticated_people_approve_server_valued_inventory_effect(db):
    prepare(db);row=request(db)
    assert row['value_cents']==300000
    for principal in ('alice-key-1','alice-key-2'):
        with pytest.raises(ValueError,match='distinct_people'):
            requests.approve_request(db,tenant_id='shop',request_id=row['id'],approver_principal=principal,now=NOW)
    grant=requests.approve_request(db,tenant_id='shop',request_id=row['id'],approver_principal='bob-key',now=NOW)
    assert grant['approval_id']
    for _ in range(2):
        result=requests.execute_request(db,tenant_id='shop',request_id=row['id'],now=NOW)
        assert result['status']=='completed'
    assert db.execute(text('SELECT on_hand FROM inventory_level')).scalar_one()==8
    assert db.execute(text('SELECT COUNT(*) FROM inventory_stock_movement')).scalar_one()==1


@pytest.mark.parametrize('change',['revoke','expire','membership','payload','tenant'])
def test_dispatch_revalidates_authority_before_stock_changes(db,change):
    prepare(db);row=request(db)
    granted=requests.approve_request(db,tenant_id='shop',request_id=row['id'],approver_principal='bob-key',now=NOW)
    if change=='revoke':person_approval.revoke(db,tenant_id='shop',approval_id=granted['approval_id'],revoked_by='admin',now=NOW)
    if change=='membership':db.execute(text("UPDATE operator_tenant_membership SET status='revoked' WHERE principal_hash='bob-key'"))
    if change=='payload':db.execute(text("UPDATE operator_inventory_request SET payload_json=replace(payload_json, 'delivery:1', 'delivery:other')"))
    with pytest.raises(ValueError):
        requests.execute_request(db,tenant_id='other' if change=='tenant' else 'shop',request_id=row['id'],
                                 now=NOW+timedelta(days=2) if change=='expire' else NOW)
    assert db.execute(text('SELECT on_hand FROM inventory_level')).scalar_one()==5


def prepare_order(db):
    from src.app.services.inventory_transactions import reserve
    prepare(db)
    db.execute(text('CREATE TABLE shopping_cases(case_id TEXT,tenant_id TEXT,revision INTEGER)'))
    db.execute(text('CREATE TABLE shopping_case_fulfillment_selections(selection_id TEXT,case_id TEXT,tenant_id TEXT,revision INTEGER)'))
    db.execute(text("INSERT INTO shopping_cases VALUES ('case','shop',2)"))
    db.execute(text("INSERT INTO shopping_case_fulfillment_selections VALUES ('sel','case','shop',2)"))
    reserve(db,tenant_id='shop',reservation_id='selection:sel:warehouse',sku='SKU',location_id='warehouse',quantity=3)
    db.commit()


def lifecycle(db,kind,reference,quantity=3):
    return requests.create_request(db,tenant_id='shop',requester_principal='alice-key-1',
        kind=kind,sku='SKU',source_reference=reference,quantity=quantity,
        reservation_id='selection:sel:warehouse',case_id='case',case_revision=2)


def approve_execute(db,row):
    requests.approve_request(db,tenant_id='shop',request_id=row['id'],approver_principal='bob-key',now=NOW)
    return requests.execute_request(db,tenant_id='shop',request_id=row['id'],now=NOW)


def test_accepted_order_ship_and_partial_return_reconcile_without_duplicate_effect(db):
    prepare_order(db)
    row=lifecycle(db,'ship','shipment:1');approve_execute(db,row)
    assert db.execute(text('SELECT on_hand FROM inventory_level')).scalar_one()==2
    returned=lifecycle(db,'return','return:1',quantity=1);approve_execute(db,returned)
    requests.execute_request(db,tenant_id='shop',request_id=returned['id'],now=NOW)
    assert db.execute(text('SELECT on_hand FROM inventory_level')).scalar_one()==3
    assert db.execute(text('SELECT returned_quantity FROM inventory_reservation')).scalar_one()==1
    assert db.execute(text('SELECT COUNT(*) FROM inventory_effect_event')).scalar_one()==3


def test_changed_case_revision_blocks_approved_shipment(db):
    prepare_order(db);row=lifecycle(db,'ship','shipment:1')
    requests.approve_request(db,tenant_id='shop',request_id=row['id'],approver_principal='bob-key',now=NOW)
    db.execute(text('UPDATE shopping_cases SET revision=3'))
    with pytest.raises(ValueError,match='case_revision'):
        requests.execute_request(db,tenant_id='shop',request_id=row['id'],now=NOW)
    assert db.execute(text('SELECT on_hand FROM inventory_level')).scalar_one()==5


def test_cancellation_releases_hold_and_wrong_case_cannot_claim_reservation(db):
    prepare_order(db)
    db.execute(text("INSERT INTO shopping_cases VALUES ('other','shop',2)"))
    with pytest.raises(ValueError,match='reservation_case'):
        requests.create_request(db,tenant_id='shop',requester_principal='alice-key-1',kind='cancel',
            sku='SKU',source_reference='wrong',quantity=3,reservation_id='selection:sel:warehouse',case_id='other',case_revision=2)
    approve_execute(db,lifecycle(db,'cancel','cancel:1'))
    assert db.execute(text('SELECT reserved FROM inventory_level')).scalar_one()==0
