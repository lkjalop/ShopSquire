"""All legacy local-demo surfaces use the same environment/peer contract."""
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request


@pytest.mark.parametrize('module,helper', [
    ('escalation_room', '_allow_public_escalation'),
    ('merchant_dashboard', '_allow_unauth_dashboard'),
    ('query_clusters', '_allow_unauth_merchant_analytics'),
])
@pytest.mark.parametrize('environment,override,peer,allowed', [
    ('local', '', '127.0.0.1', True),
    ('test', '1', '127.0.0.1', True),
    ('test', '1', '::1', True),
    ('local', '0', '127.0.0.1', False),
    ('local', 'tru', '127.0.0.1', False),
    ('test', '', '127.0.0.1', False),
    ('production', '1', '127.0.0.1', False),
    ('unknown', '1', '127.0.0.1', False),
    ('', '1', '127.0.0.1', False),
    ('test', '1', '198.51.100.27', False),
    ('local', '', '198.51.100.27', False),
])
def test_demo_admission_is_consistent(monkeypatch, module, helper, environment, override, peer, allowed):
    monkeypatch.setenv('APP_ENV', environment)
    monkeypatch.setenv('ALLOW_UNAUTH_MERCHANT_DASHBOARD', override)
    request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'scheme': 'http',
                       'query_string': b'', 'client': (peer, 1234), 'server': ('test', 80),
                       'headers': [(b'host', b'localhost')]})
    function = getattr(importlib.import_module('src.app.routers.' + module), helper)
    assert function(request) is allowed


@pytest.mark.parametrize('environment,peer', [('production', '127.0.0.1'), ('test', '198.51.100.27')])
def test_analytics_demo_cannot_read_before_normal_authentication(monkeypatch, environment, peer):
    from src.app.routers import query_clusters

    monkeypatch.setenv('APP_ENV', environment)
    monkeypatch.setenv('ALLOW_UNAUTH_MERCHANT_DASHBOARD', '1')
    reads = []

    def forbidden_read(**_kwargs):
        reads.append(True)
        raise AssertionError('An unauthenticated demo request reached dataset access')

    monkeypatch.setattr(query_clusters, 'read_session', forbidden_read)
    app = FastAPI()
    app.include_router(query_clusters.router)
    response = TestClient(app, client=(peer, 1234)).get(
        '/api/v1/analytics/query_clusters/latest', headers={'host': 'localhost'},
    )
    assert response.status_code in (401, 403)
    assert not reads
