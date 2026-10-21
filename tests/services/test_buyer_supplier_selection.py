from datetime import datetime, timedelta, timezone
import json
import pytest
from sqlalchemy import text
from tests.services.test_case_inventory_acceptance import db, accept
from tests.migration_helpers import apply_revision
from src.app.services import supplier_enquiry_journey as enquiries
from src.app.services.fulfillment import outbound_queue
from src.app.services.buyer_supplier_quotes import project_quotes
from src.app.services.buyer_supplier_selection import accept_quote, read_selection

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def prepare(db):
    apply_revision(db.get_bind(), '20260853_conversation_case_state.py')
    from src.app.models.orm import Product
    db.add(Product(id='selection-product',sku='SKU',name='Fictional configuration',
                   price_cents=100000,currency='AUD',active=True,specs={}))
    db.commit()
    accept(db, now=NOW)
    enquiries.ensure_tables(db)
    db.execute(text(outbound_queue._DDL))
    db.execute(text('''INSERT INTO supplier_enquiry_request
        (id,tenant_id,case_id,case_revision,requester_principal,supplier_ref,recipient,source_reference,
         sku,requested_quantity,shortfall,value_cents,currency,status,created_at)
        VALUES ('enquiry','synthetic-shop','case',2,'requester','fixture','quotes@example.invalid',
         'fixture','SKU',30,15,3000000,'AUD','approved',:now)'''), {'now': NOW.isoformat()})
    terms = dict(sku='SKU',quantity=15,unit_cost_cents=70000,freight_cents=12000,
                 currency='AUD',lead_days=5,minimum_order=1,expires_at=(NOW+timedelta(days=1)).isoformat())
    db.execute(text('''INSERT INTO supplier_enquiry_reply
        (id,tenant_id,enquiry_id,message_id,sender_ref,terms_json,payload_digest,status,reason,received_at)
        VALUES ('reply','synthetic-shop','enquiry','fixture','fixture',:terms,'fixture','reviewed','',:now)'''),
        {'terms':json.dumps(terms),'now':NOW.isoformat()})
    db.commit()
    apply_revision(db.get_bind(), '20260892_buyer_supplier_selection.py')
    return project_quotes(db, tenant_id='synthetic-shop', case_id='case', now=NOW)['quotes'][0]


def choose(db, quote, **overrides):
    return accept_quote(db, **{**dict(tenant_id='synthetic-shop',case_id='case',uid='buyer',
        expected_revision=2,quote_id=quote['quote_id'],expected_digest=quote['selection_digest'],now=NOW),**overrides})


def test_selection_is_explicit_replay_safe_and_has_no_commerce_effect(db):
    quote = prepare(db)
    before = db.execute(text('SELECT SUM(quantity) FROM inventory_reservation')).scalar_one()
    assert read_selection(db,tenant_id='synthetic-shop',case_id='case',uid='buyer',now=NOW)['status']=='unselected'
    first = choose(db, quote); db.commit()
    assert choose(db, quote)['selection_id'] == first['selection_id']
    assert first['commerce_authority']=='none'
    assert first['quote']['total_price_cents']==1512000
    assert first['quote']['covered_order_total_price_cents']==3012000
    assert db.execute(text('SELECT SUM(quantity) FROM inventory_reservation')).scalar_one()==before
    assert db.execute(text('SELECT COUNT(*) FROM outbound_message')).scalar_one()==0
    assert db.execute(text('SELECT COUNT(*) FROM buyer_supplier_quote_selection')).scalar_one()==1


@pytest.mark.parametrize('change',['price','inactive','freight','revision','expiry','review','shortfall','buyer','tenant'])
def test_selection_revalidates_current_quote_scope_and_price(db,change):
    quote=prepare(db); overrides={}
    if change=='price':db.execute(text('UPDATE products SET price_cents=price_cents+100'))
    if change=='inactive':db.execute(text('UPDATE products SET active=0'))
    if change=='freight':
        terms=json.loads(db.execute(text('SELECT terms_json FROM supplier_enquiry_reply')).scalar_one())
        terms['freight_cents']+=100
        db.execute(text('UPDATE supplier_enquiry_reply SET terms_json=:terms'),{'terms':json.dumps(terms)})
    if change=='revision':db.execute(text('UPDATE shopping_cases SET revision=3'))
    if change=='expiry':overrides['now']=NOW+timedelta(days=1)
    if change=='review':db.execute(text("UPDATE supplier_enquiry_reply SET status='quarantined'"))
    if change=='shortfall':db.execute(text("UPDATE inventory_reservation SET status='cancelled'"))
    if change=='buyer':overrides['uid']='another-buyer'
    if change=='tenant':overrides['tenant_id']='another-tenant'
    with pytest.raises(ValueError):choose(db,quote,**overrides)
    assert db.execute(text('SELECT COUNT(*) FROM buyer_supplier_quote_selection')).scalar_one()==0


def test_historical_selection_is_not_presented_as_current_after_price_change(db):
    quote=prepare(db);choose(db,quote);db.commit()
    db.execute(text('UPDATE products SET price_cents=price_cents+100'))
    view=read_selection(db,tenant_id='synthetic-shop',case_id='case',uid='buyer',now=NOW)
    assert view['status']=='revalidation_required'
    assert view['commerce_authority']=='none'
