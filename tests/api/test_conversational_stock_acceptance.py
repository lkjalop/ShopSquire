"""Ordinary owned cases use the same stock transactions as the showcase."""
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from src.app.models.orm import Base, Product, ShoppingCase
from src.app.models.db import get_db
from src.app.routers.shopping_cases import router
from src.app.services.electronics_shop_scenario import seed_scenario
from src.app.services.inventory_transactions import ensure_tables
from tests.buyer_client import BuyerTestClient, TEST_SIGNING_KEY


def test_normal_case_stock_acceptance_is_owned_revision_bound_and_reconciled(monkeypatch):
    monkeypatch.setenv('JWT_SIGNING_KEY', TEST_SIGNING_KEY)
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON', '{"buyer":["synthetic-electronics"],"other":["synthetic-electronics"]}')
    monkeypatch.setenv('ENABLE_DEMO_ROUTES', '1')
    engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    from tests.migration_helpers import apply_revision
    apply_revision(engine,'20260892_buyer_supplier_selection.py')
    with Session(engine) as db:
        ensure_tables(db)
        from src.app.services.supplier_enquiry_journey import ensure_tables as ensure_enquiries
        ensure_enquiries(db)
        db.add(Product(sku='DISPLAY-1',name='Unfamiliar display',price_cents=10000,specs={}))
        seed_scenario(db,tenant_id='synthetic-electronics',sku='DISPLAY-1',retail_cents=10000)
        db.add(ShoppingCase(case_id='normal-case',uid='buyer',tenant_id='synthetic-electronics',revision=1,
            retained_purpose='Buyer asked about office displays'))
        db.commit()
        initial_reserved = db.execute(text('SELECT SUM(reserved) FROM inventory_level')).scalar()
        app=FastAPI();app.include_router(router);app.dependency_overrides[get_db]=lambda:db
        from src.app.platform.tenant_context import set_active_tenant_id,reset_active_tenant_id
        @app.middleware('http')
        async def scope(request,call_next):
            token=set_active_tenant_id(request.headers.get('x-tenant-id'))
            try:return await call_next(request)
            finally:reset_active_tenant_id(token)
        path='/api/v1/shopping-cases/normal-case'
        body=dict(uid='buyer',expected_revision=1,sku='DISPLAY-1',quantity=30,idempotency_key='normal-accept-30')
        with BuyerTestClient(app,headers={'X-Tenant-ID':'synthetic-electronics'}) as client:
            selection=dict(uid='buyer',expected_revision=1,quote_id='nonexistent',expected_digest='a'*64)
            assert client.get(path+'/supplier-quote-selection',params={'uid':'buyer'},headers={'Authorization':''}).status_code==401
            assert client.get(path+'/supplier-quote-selection',params={'uid':'other'}).status_code==403
            assert client.get(path+'/supplier-quote-selection',params={'uid':'buyer'}).json()['status']=='unselected'
            assert client.post(path+'/supplier-quote-selection',json=selection,headers={'Authorization':''}).status_code==401
            assert client.post(path+'/supplier-quote-selection',json={**selection,'uid':'other'}).status_code==403
            assert client.post(path+'/supplier-quote-selection',json=selection).status_code==409
            assert db.execute(text('SELECT COUNT(*) FROM buyer_supplier_quote_selection')).scalar()==0
            assert client.get(path+'/supplier-quotes',params={'uid':'buyer'},headers={'Authorization':''}).status_code==401
            assert client.get(path+'/supplier-quotes',params={'uid':'other'}).status_code==403
            assert client.get(path+'/supplier-quotes',params={'uid':'buyer'}).json()['status']=='no_enquiry'
            assert client.post(path+'/stock-acceptance',json=body,headers={'Authorization':''}).status_code==401
            assert client.post(path+'/stock-acceptance',json={**body,'uid':'other'}).status_code==403
            result=client.post(path+'/stock-acceptance',json=body)
            assert result.status_code==200,result.text
            assert result.json()['held_quantity']==15
            assert result.json()['shortfall']==15
            assert result.json()['purchase_commitment'] is False
            assert client.post(path+'/stock-acceptance',json=body).json()==result.json()
            snapshot=client.get(path+'/stock',params={'uid':'buyer','sku':'DISPLAY-1'})
            assert snapshot.json()['accepted']['requested_quantity']==30
            assert snapshot.json()['accepted']['held_quantity']==15
            assert client.post(path+'/stock-acceptance',json={**body,'quantity':40}).status_code==409
            amended=client.post(path+'/stock-acceptance',json={**body,'quantity':40,'expected_revision':2,'idempotency_key':'normal-accept-40'})
            assert amended.status_code==200,amended.text
            assert amended.json()['shortfall']==25
            assert client.post(path+'/release-holds',json={'uid':'buyer','expected_revision':3}).status_code==200
            assert db.execute(text('SELECT SUM(reserved) FROM inventory_level')).scalar()==initial_reserved
            monkeypatch.setenv('ENABLE_DEMO_ROUTES','0')
            assert client.post(path+'/stock-acceptance',json=body).status_code==404
    engine.dispose()
