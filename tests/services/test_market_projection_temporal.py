"""Canonical producer facts retain event-time and current-stock boundaries."""
from datetime import datetime,timedelta,timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.models.db import create_runtime_engine
from src.app.services import market_projection as market
from src.app.services.market_facts import record_atp_fact,record_marketing_event,sign_fact
from tests.services.test_canonical_fact_adapters import _migration

NOW=datetime(2026,10,22,1,tzinfo=timezone.utc)
SECRET='owned-temporal-producer-test-secret'


@pytest.fixture()
def db(tmp_path,monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(market,'datetime',Clock)
    monkeypatch.setenv('MARKET_SOURCE_ERP_SECRET',SECRET)
    monkeypatch.setenv('MARKET_SOURCE_NETSUITE_SECRET',SECRET)
    engine=create_runtime_engine('sqlite:///'+(tmp_path/'facts.sqlite3').as_posix())
    try:
        with Session(engine) as session:
            for name in ('20260721_market_fact_contract.py','20260722_market_fact_governance.py','20260723_market_fact_quarantine_dedup.py'):
                _migration(session,name,'temporal_'+name[:-3])
            session.commit()
            yield session
    finally:
        engine.dispose()


def atp(db,record='current',**patch):
    fact=dict(tenant_id='tenant-owned',deduplication_id='erp:'+record,source_system='erp',
        source_record_id=record,sku='OWNED-1',location_id='warehouse',on_hand_quantity=10,
        committed_quantity=3,safety_stock_quantity=2,confirmed_quantity=99,
        confirmed_date=(NOW+timedelta(days=7)).isoformat(),
        observed_at=(NOW-timedelta(hours=1)).isoformat(),confidence=1,
        valid_from=(NOW-timedelta(hours=2)).isoformat(),valid_to=(NOW+timedelta(hours=2)).isoformat(),
        provenance_chain=['erp/warehouse/'+record])|patch
    fact['signature']=sign_fact(fact,SECRET)
    assert record_atp_fact(db,fact,now=NOW)
    return fact


def load(db):
    return market.load_projection_inputs(db,tenant_id='tenant-owned')


def test_signed_current_snapshot_uses_on_hand_minus_commitments_and_safety(db):
    atp(db)
    before=db.execute(text('SELECT * FROM inventory_atp_fact')).all()
    result=load(db)
    assert result['inventory_status']=='observed'
    row,=result['inventory']
    assert row['available']==5
    assert row['source_system']=='erp' and row['source_record_id']=='current'
    assert db.execute(text('SELECT * FROM inventory_atp_fact')).all()==before


@pytest.mark.parametrize('patch',[
    {'observed_at':(NOW+timedelta(seconds=60)).isoformat()},
    {'valid_to':(NOW-timedelta(seconds=1)).isoformat()},
    {'valid_to':NOW.isoformat()},
    {'valid_from':(NOW+timedelta(hours=1)).isoformat()},
    {'valid_to':'malformed-expiry'},
    {'valid_from':'malformed-start'},
])
def test_invalid_newer_snapshot_cannot_shadow_current_signed_snapshot(db,patch):
    atp(db,'current',observed_at=(NOW-timedelta(hours=3)).isoformat(),confirmed_quantity=5)
    atp(db,'invalid-newer',**({'observed_at':(NOW-timedelta(minutes=10)).isoformat()}|patch))
    rows=load(db)['inventory']
    assert [row['source_record_id'] for row in rows]==['current']
    assert rows[0]['available']==5


def test_snapshot_order_compares_instants_across_offsets(db):
    older=(NOW-timedelta(hours=2)).astimezone(timezone(timedelta(hours=10)))
    atp(db,'older-offset',observed_at=older.isoformat(),confirmed_quantity=1)
    atp(db,'current',confirmed_quantity=5)
    row,=load(db)['inventory']
    assert row['source_record_id']=='current'


def test_start_inclusive_and_no_validity_fields_use_bounded_observation(db):
    atp(db,'start-now',valid_from=NOW.isoformat(),confirmed_quantity=5)
    assert load(db)['inventory'][0]['source_record_id']=='start-now'
    atp(db,'legacy',location_id='second',valid_from=None,valid_to=None,confirmed_quantity=5)
    assert {row['source_record_id'] for row in load(db)['inventory']}=={'start-now','legacy'}


def test_missing_on_hand_does_not_promote_a_future_order_confirmation_to_stock(db):
    atp(db,on_hand_quantity=None)
    result=load(db)
    assert result['inventory']==[]
    assert result['inventory_status']=='insufficient_data'


def test_foreign_tenant_snapshot_cannot_shadow_owned_stock(db):
    atp(db,'current',confirmed_quantity=5)
    atp(db,'foreign',tenant_id='tenant-foreign',observed_at=NOW.isoformat(),confirmed_quantity=1000)
    assert [row['source_record_id'] for row in load(db)['inventory']]==['current']


@pytest.mark.parametrize('offset,expected',[(timedelta(seconds=60),[]),(timedelta(days=-1),['sale'])])
def test_sales_window_never_counts_a_future_event(db,offset,expected):
    fact=dict(tenant_id='tenant-owned',deduplication_id='netsuite:sale',source_system='netsuite',
        source_record_id='sale',event_type='purchase',sku='OWNED-1',quantity=4,
        occurred_at=(NOW+offset).isoformat(),provenance_chain=['netsuite/order/sale'])
    fact['signature']=sign_fact(fact,SECRET)
    assert record_marketing_event(db,fact,now=NOW)
    assert [row['source_record_id'] for row in load(db)['sales']]==expected
