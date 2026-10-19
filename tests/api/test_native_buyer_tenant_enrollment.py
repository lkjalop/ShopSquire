from uuid import uuid4

from fastapi.testclient import TestClient

from src.app.main import create_app


def test_native_signup_enrolls_only_its_server_recorded_storefront_tenant(monkeypatch):
    monkeypatch.setenv('BUYER_IDENTITY_MODE', 'strict')
    monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON', '{}')
    monkeypatch.setenv('JWT_SIGNING_KEY', 'native-tenant-test-signing-key-at-least-32-bytes')
    tenant = 'native-' + uuid4().hex
    with TestClient(create_app()) as client:
        response = client.post('/api/v1/auth/register', headers={'x-tenant-id':tenant},
            json={'email':uuid4().hex+'@example.com', 'name':'Fixture buyer', 'password':'NativeFixture-739!x'})
        assert response.status_code == 200, response.text
        user = response.json()
        headers = {'x-tenant-id':tenant, 'Authorization':'Bearer '+user['access_token']}
        own = client.get('/api/v1/cart', params={'uid':user['user_id']}, headers=headers)
        assert own.status_code == 200, own.text
        for foreign in (tenant+'-foreign', 'default'):
            denied = client.get('/api/v1/cart', params={'uid':user['user_id']},
                headers={**headers,'x-tenant-id':foreign})
            assert denied.status_code == 403, denied.text
        # Explicit deployment bindings remain authoritative even when a native
        # customer row exists; revocation must not silently fall through.
        monkeypatch.setenv('BUYER_TENANT_BINDINGS_JSON', '{"'+user['user_id']+'":[]}')
        assert client.get('/api/v1/cart', params={'uid':user['user_id']}, headers=headers).status_code == 403
