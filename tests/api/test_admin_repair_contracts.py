from fastapi import FastAPI
from fastapi.testclient import TestClient
from inspect import signature
from src.app.routers import merchant_intelligence


def test_trusted_claims_optional_filters_return_typed_envelope(monkeypatch):
    from src.app.services import citation_memory
    observed = []
    def claims(agent, kind, **kwargs):
        observed.append((agent, kind, kwargs))
        return [{'id': 'c1', 'agent_name': 'agent-a', 'claim_type': 'stock', 'claim_key': 'sku',
                 'claim_value': 2, 'trust_score': .9, 'confidence': .8}]
    monkeypatch.setattr(citation_memory, 'get_trusted_claims', claims)
    app = FastAPI()
    app.include_router(merchant_intelligence.router)
    role_dependency = signature(merchant_intelligence.trusted_claims).parameters['role'].default.dependency
    app.dependency_overrides[role_dependency] = lambda: 'owner'
    with TestClient(app) as client:
        response = client.get('/api/v1/merchant/intelligence/citation_memory/trusted_claims')
    assert response.status_code == 200
    assert response.json()['claims'][0]['claim_key'] == 'sku'
    assert observed[0][0:2] == (None, None)
    assert observed[0][2]['strict'] is True


def test_trusted_claims_backend_failure_is_not_an_empty_success(monkeypatch):
    from src.app.services import citation_memory
    def unavailable(*args, **kwargs):
        assert kwargs['strict'] is True
        raise ConnectionError('unavailable')
    monkeypatch.setattr(citation_memory, 'get_trusted_claims', unavailable)
    app = FastAPI()
    app.include_router(merchant_intelligence.router)
    role_dependency = signature(merchant_intelligence.trusted_claims).parameters['role'].default.dependency
    app.dependency_overrides[role_dependency] = lambda: 'owner'
    with TestClient(app) as client:
        response = client.get('/api/v1/merchant/intelligence/citation_memory/trusted_claims')
    assert response.status_code == 500
    assert 'claims' not in response.json()


def test_trusted_claims_still_requires_authentication():
    app = FastAPI()
    app.include_router(merchant_intelligence.router)
    with TestClient(app) as client:
        response = client.get('/api/v1/merchant/intelligence/citation_memory/trusted_claims')
    assert response.status_code == 401
