from datetime import timedelta
import json
from sqlalchemy import text
from tests.services.test_supplier_enquiry_journey import db, sent, quote, NOW
from src.app.services import supplier_enquiry_journey as journey


def test_buyer_quote_projection_is_scoped_reviewed_and_uses_retail_prices(db):
    from src.app.services.buyer_supplier_quotes import project_quotes
    enquiry, transport = sent(db)
    terms=quote();terms['quantity']=10
    reply=journey.receive(db,tenant_id='shop',enquiry_id=enquiry['id'],message_id='buyer-quote',
        sender_ref='fictional-distributor',terms=terms,now=NOW)
    assert project_quotes(db,tenant_id='shop',case_id='case',now=NOW)['quotes']==[]
    journey.review(db,tenant_id='shop',enquiry_id=enquiry['id'],reply_id=reply['id'],reviewer_principal='bob-key',now=NOW)
    view=project_quotes(db,tenant_id='shop',case_id='case',now=NOW)
    row=view['quotes'][0]
    assert row['quantity']==10 and row['uncovered_quantity']==5
    assert row['unit_price_cents']==100000 and row['total_price_cents']==1012000
    assert row['coverage']=='partial' and row['eligible'] is True
    assert row['commerce_authority']=='none'
    assert 'unit_cost_cents' not in json.dumps(view)
    assert 'quotes@fixture.invalid' not in json.dumps(view)
    assert 'bob-key' not in json.dumps(view)
    assert project_quotes(db,tenant_id='other',case_id='case',now=NOW)['quotes']==[]
    assert project_quotes(db,tenant_id='shop',case_id='other',now=NOW)['quotes']==[]
    assert transport.calls==1


def test_buyer_quote_revalidates_expiry_shortfall_and_revision(db):
    from src.app.services.buyer_supplier_quotes import project_quotes
    enquiry,_=sent(db)
    reply=journey.receive(db,tenant_id='shop',enquiry_id=enquiry['id'],message_id='reply',
        sender_ref='fictional-distributor',terms=quote(),now=NOW)
    journey.review(db,tenant_id='shop',enquiry_id=enquiry['id'],reply_id=reply['id'],reviewer_principal='bob-key',now=NOW)
    initial=project_quotes(db,tenant_id='shop',case_id='case',now=NOW)['quotes'][0]
    assert initial['eligible']
    db.execute(text("UPDATE inventory_reservation SET expires_at=:expiry"),{'expiry':(NOW+timedelta(days=2)).isoformat()})
    expired=project_quotes(db,tenant_id='shop',case_id='case',now=NOW+timedelta(days=1))['quotes'][0]
    assert not expired['eligible'] and expired['reason']=='quote_expired'
    db.execute(text('UPDATE shopping_cases SET revision=3'))
    stale=project_quotes(db,tenant_id='shop',case_id='case',now=NOW)['quotes'][0]
    assert not stale['eligible'] and stale['reason']=='stale_case_revision'
    assert stale['total_price_cents'] is None
