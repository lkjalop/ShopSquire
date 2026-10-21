from datetime import datetime,timezone,timedelta
import json
from fastapi import FastAPI
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from src.app.models.db import get_db
from src.app.models.orm import Base,Product,ProductConfiguration,ProductEvidenceObservation,ShoppingCase
from src.app.routers.shopping_cases import router
from src.app.services import governed_product_offers as offers
from src.app.services.inventory_transactions import ensure_tables
from src.app.services.commerce_catalog import upsert_inventory
from tests.buyer_client import BuyerTestClient,TEST_SIGNING_KEY


def test_normal_case_offer_changes_only_owned_cart_after_explicit_acceptance(monkeypatch):
    monkeypatch.setenv('JWT_SIGNING_KEY',TEST_SIGNING_KEY)
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON','{"buyer":["shop"]}')
    engine=create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine);now=datetime.now(timezone.utc)
    with Session(engine) as db:
        # These production columns are migration-owned, not in the legacy ORM.
        db.execute(text("ALTER TABLE draft_orders ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default'"))
        db.execute(text('ALTER TABLE draft_orders ADD COLUMN version INTEGER NOT NULL DEFAULT 0'))
        ensure_tables(db);db.execute(text(offers.DDL))
        for sku,price in [('DISPLAY',10000),('STAND',2000)]:
            db.add(Product(id=sku,sku=sku,name=sku,price_cents=price,currency='AUD'))
            db.add(ProductConfiguration(id=sku,tenant_id='shop',sku=sku,title=sku,configuration_hash=sku,
                price_cents=price,currency='AUD',price_observed_at=now))
            upsert_inventory(db,tenant_id='shop',sku=sku,location_id='store',on_hand=10,reserved=0)
        db.add(ShoppingCase(case_id='case',tenant_id='shop',uid='buyer',revision=1))
        db.add(ProductEvidenceObservation(id='pair',configuration_id='DISPLAY',attribute_key='supported_product_relation',
            value_json=dict(target_configuration_id='STAND',kind='cross_sell',need='height_adjustment',supported=True,benefit='Supports the exact fixture display mounting.'),
            claim_class='attested',evidence_status='observed',source_id='fixture:mounting',source_record_id='pair',
            source_excerpt='Supports the exact fixture display mounting.',observed_at=now,expires_at=now+timedelta(days=1)))
        db.execute(text("INSERT INTO draft_orders(id,tenant_id,customer_id,status,line_items,version) VALUES ('cart','shop','buyer','draft','[]',0)"));db.commit()
        app=FastAPI();app.include_router(router);app.dependency_overrides[get_db]=lambda:db
        from src.app.platform.tenant_context import set_active_tenant_id,reset_active_tenant_id
        @app.middleware('http')
        async def scope(request,call_next):
            token=set_active_tenant_id(request.headers.get('x-tenant-id'))
            try:return await call_next(request)
            finally:reset_active_tenant_id(token)
        path='/api/v1/shopping-cases/case'
        with BuyerTestClient(app,headers={'x-tenant-id':'shop'}) as client:
            params={'uid':'buyer','sku':'DISPLAY'}
            assert client.get(path+'/product-offer-options',params=params,headers={'Authorization':''}).status_code==401
            options=client.get(path+'/product-offer-options',params=params)
            assert options.status_code==200,options.text
            assert options.json()['candidates'][0]['sku']=='STAND'
            payload=dict(uid='buyer',expected_revision=1,base_configuration_id='DISPLAY',target_configuration_id='STAND',need='height_adjustment',quantity=2)
            proposed=client.post(path+'/product-offers',json=payload)
            assert proposed.status_code==200,proposed.text
            offer=proposed.json();assert offer['total_cents']==24000
            assert db.execute(text('SELECT version FROM draft_orders')).scalar()==0
            accepted=client.post(path+'/product-offers/'+offer['id']+'/accept',json={'uid':'buyer'})
            assert accepted.status_code==200,accepted.text
            assert accepted.json()['case_revision']==2
            assert db.execute(text('SELECT version FROM draft_orders')).scalar()==1
            assert len(json.loads(db.execute(text('SELECT line_items FROM draft_orders')).scalar()))==2
            assert client.post(path+'/product-offers/'+offer['id']+'/accept',json={'uid':'buyer'}).json()==accepted.json()
            assert db.execute(text('SELECT version FROM draft_orders')).scalar()==1
            db.get(ProductEvidenceObservation,'pair').evidence_status='revoked';db.commit()
            assert client.get(path+'/product-offer-options',params=params).json()['candidates']==[]
    engine.dispose()
