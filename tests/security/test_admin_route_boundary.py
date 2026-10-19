from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.app.security.admin_route_boundary import enforce_admin_route_boundary


def test_nested_admin_include_is_guarded_without_changing_the_public_include(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'test')
    endpoints = APIRouter()

    @endpoints.get('/ping')
    def ping():
        return {'ok': True}

    nested = APIRouter(prefix='/api/v1')
    nested.include_router(endpoints, prefix='/admin')
    nested.include_router(endpoints, prefix='/public')
    app = FastAPI()
    app.include_router(nested)
    enforce_admin_route_boundary(app)
    enforce_admin_route_boundary(app)

    with TestClient(app) as client:
        assert client.get('/api/v1/public/ping').status_code == 200
        assert client.get('/api/v1/admin/ping').status_code in (401, 403)
        allowed = client.get('/api/v1/admin/ping', headers={'x-api-key': 'local-merchant-key'})
        assert allowed.status_code == 200, allowed.text
        assert client.get('/api/v1/public/ping').status_code == 200
