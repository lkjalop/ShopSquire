import time
import jwt
import pytest
from fastapi.testclient import TestClient
from src.app.main import create_app


@pytest.fixture
def buyer(monkeypatch):
    monkeypatch.setenv('JWT_SIGNING_KEY', 'native-buyer-surface-test-key')
    monkeypatch.setenv('BUYER_IDENTITY_MODE', 'strict')
    now = int(time.time())
    token = jwt.encode({'sub': 'native-buyer-scope', 'typ': 'access', 'role': 'buyer',
        'iss': 'shopsquire', 'aud': 'shopsquire-api', 'iat': now, 'exp': now+300},
        'native-buyer-surface-test-key', algorithm='HS256')
    client = TestClient(create_app())
    client.cookies.set('shopsquire_access', token)
    return client


def test_native_buyer_can_read_own_cart_without_operator_key(buyer):
    response = buyer.get('/api/v1/cart', params={'uid': 'native-buyer-scope'})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('method,path,payload', [
    ('get', '/api/v1/cart', {'uid': 'other-buyer'}),
    ('get', '/api/v1/chat/history', {'uid': 'other-buyer'}),
    ('post', '/api/v1/chat/query', {'uid': 'other-buyer', 'query': 'Recall my budget'}),
    ('post', '/api/v1/chat/stream', {'uid': 'other-buyer', 'query': 'Recall my budget'}),
])
def test_native_buyer_cannot_impersonate_another_customer(buyer, method, path, payload):
    response = getattr(buyer, method)(path, **({'params': payload} if method=='get' else {'json': payload}))
    assert response.status_code == 403, response.text


def test_native_buyer_cannot_select_foreign_tenant(buyer):
    response = buyer.get('/api/v1/cart', params={'uid': 'native-buyer-scope'}, headers={'x-tenant-id': 'foreign-shop'})
    assert response.status_code == 403, response.text


def test_public_accounts_never_inherit_a_default_operator_role(monkeypatch):
    from src.app.routers.auth import _jwt_default_role
    monkeypatch.setenv('LOCAL_AUTH_DEFAULT_ROLE', 'owner')
    assert _jwt_default_role() == 'buyer'
