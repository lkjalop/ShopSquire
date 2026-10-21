import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import get_db
from src.app.models.orm import Base, ShoppingCase
from src.app.routers.shopping_cases import router


@pytest.fixture
def client(monkeypatch):
    import time,jwt
    from src.app.platform.tenant_context import set_active_tenant_id,reset_active_tenant_id
    monkeypatch.setenv('JWT_SIGNING_KEY','test-case-identity-key-not-for-deployment')
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON','{"buyer":["tenant"]}')
    engine = create_engine('sqlite:///:memory:',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ShoppingCase(case_id='case',tenant_id='tenant',uid='buyer',revision=1))
        db.commit()
        app = FastAPI()
        @app.middleware('http')
        async def tenant_context(request,call_next):
            token=set_active_tenant_id(request.headers.get('x-tenant-id'))
            try:return await call_next(request)
            finally:reset_active_tenant_id(token)
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        now=int(time.time())
        token=jwt.encode(dict(sub='buyer',typ='access',iss='shopsquire',aud='shopsquire-api',iat=now,exp=now+300),
                         'test-case-identity-key-not-for-deployment',algorithm='HS256')
        with TestClient(app,headers={'X-Tenant-ID':'tenant','Authorization':'Bearer '+token}) as http:
            yield http
    engine.dispose()


def test_select_reload_stale_writer_and_revoke(client):
    path='/api/v1/shopping-cases/case/requirement-contract'
    initial=client.get(path,params={'uid':'buyer'})
    assert initial.status_code == 200
    contract=initial.json()['contracts'][0]
    body=dict(uid='buyer',expected_revision=1,contract_id=contract['id'],
              contract_revision=contract['revision'],context=contract['context'])
    chosen=client.put(path,json=body)
    assert chosen.status_code == 200
    selection=chosen.json()['selection']
    assert selection['state'] == 'current'
    assert client.get(path,params={'uid':'buyer'}).json()['selection']==selection
    assert client.put(path,json=body).status_code == 409
    revoked=client.post(path+'/revoke',json=dict(uid='buyer',expected_revision=2,binding_id=selection['binding_id']))
    assert revoked.status_code == 200
    assert revoked.json()['selection']['state']=='revoked'


@pytest.mark.parametrize('tenant,uid,status',[('other','buyer',403),('tenant','other',403)])
def test_scope_cannot_read_contract_selection(client,tenant,uid,status):
    assert client.get('/api/v1/shopping-cases/case/requirement-contract',params={'uid':uid},
                      headers={'X-Tenant-ID':tenant}).status_code == status


def test_outdated_contract_document_cannot_be_selected(client):
    path='/api/v1/shopping-cases/case/requirement-contract'
    contract=client.get(path,params={'uid':'buyer'}).json()['contracts'][0]
    result=client.put(path,json=dict(uid='buyer',expected_revision=1,contract_id=contract['id'],
                                    contract_revision='obsolete',context=contract['context']))
    assert result.status_code == 409
    assert client.get(path,params={'uid':'buyer'}).json()['selection']['case_revision']==1


def test_copied_uid_is_not_authentication(client):
    path='/api/v1/shopping-cases/case/requirement-contract'
    assert client.get(path,params={'uid':'buyer'},headers={'Authorization':''}).status_code==401
    result=client.post('/api/v1/shopping-cases/copied/requirement-proposals/from-text',
                      json={'uid':'buyer','text':'RAM 32GB minimum'},headers={'Authorization':''})
    assert result.status_code==401
