from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.shortfall_enquiry_preview import remaining_shortfall, shortfall_draft


NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


@pytest.fixture
def selection_db():
    engine = create_engine('sqlite://')
    with Session(engine) as db:
        db.execute(text('CREATE TABLE shopping_case_fulfillment_selections '
            '(tenant_id TEXT,case_id TEXT,revision INTEGER,selection_id TEXT,preferred_sku TEXT,requested_quantity INTEGER)'))
        db.execute(text("INSERT INTO shopping_case_fulfillment_selections VALUES ('shop','case',1,'sel_%','SKU',40)"))
        db.execute(text('CREATE TABLE inventory_reservation '
            '(tenant_id TEXT,reservation_id TEXT,quantity INTEGER,status TEXT,expires_at TEXT)'))
        yield db
    engine.dispose()


@pytest.mark.parametrize('status,expiry,expected', [
    ('reserved', (NOW + timedelta(hours=1)).isoformat(), 15),
    ('reserved', (NOW - timedelta(hours=1)).isoformat(), 40),
    ('reserved', '2026-10-20T10:00:00+11:00', 40),
    ('shipped', None, 15), ('returned', None, 15), ('released', None, 40),
])
def test_exact_shortfall_uses_current_tenant_selection_and_coverage(selection_db, status, expiry, expected):
    db = selection_db
    db.execute(text("INSERT INTO inventory_reservation VALUES ('shop',:id,25,:status,:expiry)"),
        dict(id='selection:sel_%:owned', status=status, expiry=expiry))
    # Same-looking IDs and foreign tenants must never cover this buyer's demand.
    db.execute(text("INSERT INTO inventory_reservation VALUES ('other',:id,400,'shipped',NULL)"),
        {'id': 'selection:sel_%:foreign'})
    db.execute(text("INSERT INTO inventory_reservation VALUES ('shop',:id,400,'shipped',NULL)"),
        {'id': 'selection:selXY:other'})
    assert remaining_shortfall(db, tenant_id='shop', case_id='case', revision=1, now=NOW) == expected


def test_new_quantity_requires_a_current_accepted_selection(selection_db):
    draft = shortfall_draft(selection_db, tenant_id='shop', case_id='case', revision=1,
        state={'requested_quantity': 50}, now=NOW)
    assert draft['shortfall'] is None
    assert 'current_accepted_selection' in draft['missing_inputs']
    assert '50 units' in draft['body']


def test_fully_covered_demand_does_not_draft_a_zero_quantity_quote(selection_db):
    selection_db.execute(text("INSERT INTO inventory_reservation VALUES ('shop',:id,40,'shipped',NULL)"),
        {'id': 'selection:sel_%:owned'})
    draft = shortfall_draft(selection_db, tenant_id='shop', case_id='case', revision=1,
        state={'requested_quantity': 40}, now=NOW)
    assert draft['shortfall'] == 0 and draft['status'] == 'no_shortfall'
    assert 'quote' not in draft['body'].lower()
