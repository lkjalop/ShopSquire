import time
import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.app.routers.product_offer_demo import router
from tests.buyer_client import TEST_SIGNING_KEY


def test_offer_routes_reject_unverified_spoofed_and_wrong_tenant_buyers(monkeypatch):
    monkeypatch.setenv('ENABLE_DEMO_ROUTES','1')
    monkeypatch.setenv('JWT_SIGNING_KEY',TEST_SIGNING_KEY)
    monkeypatch.setenv('BUYER_IDENTITY_MODE','strict')
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON','{"buyer":["synthetic-bundles","other"]}')
    app=FastAPI();app.include_router(router)
    from src.app.platform.tenant_context import set_active_tenant_id,reset_active_tenant_id
    @app.middleware('http')
    async def scope(request,call_next):
        token=set_active_tenant_id(request.headers.get('x-tenant-id'))
        try:return await call_next(request)
        finally:reset_active_tenant_id(token)
    now=int(time.time())
    token=jwt.encode(dict(sub='buyer',typ='access',iss='shopsquire',aud='shopsquire-api',iat=now,exp=now+300),TEST_SIGNING_KEY,algorithm='HS256')
    with TestClient(app) as client:
        for suffix in ['', '/case/offers/offer/accept','/case/offers/offer/decline']:
            assert client.post('/product-offer-cases'+suffix,json={'uid':'buyer'},headers={'x-tenant-id':'synthetic-bundles'}).status_code==401
            assert client.post('/product-offer-cases'+suffix,json={'uid':'someone-else'},headers={'x-tenant-id':'synthetic-bundles','authorization':'Bearer '+token}).status_code==403
            assert client.post('/product-offer-cases'+suffix,json={'uid':'buyer'},headers={'x-tenant-id':'other','authorization':'Bearer '+token}).status_code==403
