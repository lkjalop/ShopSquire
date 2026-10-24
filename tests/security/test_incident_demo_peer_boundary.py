"""An untrusted Host header cannot enable the local incident demonstration."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.app.routers.escalation_room import _allow_public_escalation, public_router


@pytest.mark.parametrize('environment,override,peer,host', [
    ('production', '1', '127.0.0.1', 'localhost'),
    ('unknown', '1', '127.0.0.1', 'localhost'),
    ('test', '0', '127.0.0.1', 'localhost'),
    ('test', '1', '198.51.100.27', 'localhost'),
    ('test', '1', '198.51.100.27', '127.0.0.1.attacker.invalid'),
])
def test_disabled_or_remote_demo_admission_rejects_before_incident_creation(
    monkeypatch, environment, override, peer, host,
):
    monkeypatch.setenv('APP_ENV', environment)
    monkeypatch.setenv('ALLOW_UNAUTH_MERCHANT_DASHBOARD', override)
    request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'scheme': 'http',
                       'query_string': b'', 'client': (peer, 1234), 'server': ('test', 80),
                       'headers': [(b'host', host.encode())]})
    assert not _allow_public_escalation(request)
    app = FastAPI()
    app.include_router(public_router)
    response = TestClient(app, client=(peer, 1234)).post(
        '/api/v1/incidents/escalate', headers={'host': host},
        json={'case_id': 'must-not-create', 'trace_id': 'must-not-create', 'reason': 'boundary'},
    )
    assert response.status_code == 403
    assert response.json()['detail'] == 'public_escalation_disabled'


@pytest.mark.parametrize('peer', ['127.0.0.1', '::1'])
def test_explicit_local_demo_keeps_the_loopback_positive(monkeypatch, peer):
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('ALLOW_UNAUTH_MERCHANT_DASHBOARD', '1')
    request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'scheme': 'http',
                       'query_string': b'', 'client': (peer, 1234), 'server': ('test', 80),
                       'headers': [(b'host', b'localhost')]})
    assert _allow_public_escalation(request)
