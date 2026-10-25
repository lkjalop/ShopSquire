import os
import base64
import json
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request


def test_forged_bearer_cannot_supply_operator_identity(monkeypatch):
    from src.app.security import auth
    payload = base64.urlsafe_b64encode(json.dumps({'sub': 'another-tenant-owner',
        'email': 'owner@example.test'}).encode()).decode().rstrip('=')
    bearer = 'Bearer e30.' + payload + '.invalid'
    monkeypatch.setattr(auth, '_verify_local_jwt', lambda _: None)
    monkeypatch.setattr(auth, '_verify_oidc_jwt', lambda _: None)
    monkeypatch.setattr(auth, '_introspect_token', lambda _: None)
    assert auth.operator_subject(bearer) == auth.OperatorSubject()


def test_verified_bearer_retains_operator_identity(monkeypatch):
    import jwt
    import time
    from src.app.security import auth
    key = 'fixture-' + os.urandom(32).hex()
    monkeypatch.setenv('JWT_SIGNING_KEY', key)
    monkeypatch.setenv('JWT_ISSUER', 'shopsquire')
    monkeypatch.setenv('JWT_AUDIENCE', 'shopsquire-api')
    token = jwt.encode({'sub': 'operator-a', 'role': 'merchant', 'iss': 'shopsquire',
        'aud': 'shopsquire-api', 'exp': int(time.time()) + 60, 'iat': int(time.time())}, key, algorithm='HS256')
    assert auth.operator_subject('Bearer ' + token).user_id == 'operator-a'


def test_escalation_demo_override_cannot_bypass_unknown_environment(monkeypatch):
    from src.app.routers.escalation_room import _allow_public_escalation
    request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'scheme': 'http',
        'query_string': b'', 'client': ('127.0.0.1', 1234), 'server': ('test', 80), 'headers': []})
    monkeypatch.delenv('APP_ENV', raising=False)
    monkeypatch.setenv('ALLOW_UNAUTH_MERCHANT_DASHBOARD', '1')
    assert not _allow_public_escalation(request)


def test_registered_admin_api_routes_all_have_baseline_authorization():
    from src.app.main import create_app
    from src.app.security.admin_route_boundary import admin_operator
    from fastapi.routing import APIRoute, iter_route_contexts
    routes = [r for r in iter_route_contexts(create_app().routes)
              if isinstance(r.route, APIRoute) and r.path.startswith('/api/v1/admin/')]
    assert routes
    assert all(any(dep.call is admin_operator for dep in r.dependant.dependencies) for r in routes)


def test_admin_registration_guard_runs_before_unguarded_handler():
    from src.app.security.admin_route_boundary import enforce_admin_route_boundary
    app = FastAPI()
    executed = []
    @app.get('/api/v1/admin/accidentally-public')
    def forgotten_guard():
        executed.append(True)
        return {'secret': True}
    enforce_admin_route_boundary(app)
    response = TestClient(app).get('/api/v1/admin/accidentally-public')
    assert response.status_code in (401, 403)
    assert not executed


def test_unknown_environment_never_supplies_known_role_credentials(monkeypatch):
    from src.app.security.auth import _env_role_key
    monkeypatch.delenv('OWNER_API_KEY', raising=False)
    for env in (None, '', 'production', 'prodution'):
        if env is None:
            monkeypatch.delenv('APP_ENV', raising=False)
        else:
            monkeypatch.setenv('APP_ENV', env)
        assert _env_role_key('OWNER_API_KEY', 'local-owner-key') == ''


def test_dmarc_unauthenticated_request_cannot_execute_summary(monkeypatch):
    from src.app.routers import admin_dmarc
    app = FastAPI()
    app.include_router(admin_dmarc.router)
    with patch.object(admin_dmarc, 'get_summary') as summary:
        response = TestClient(app).get('/api/v1/admin/dmarc/summary?threshold_fail_rate=0')
    assert response.status_code in (401, 403)
    summary.assert_not_called()


def test_host_header_never_establishes_local_peer_identity():
    from src.app.routers.merchant_dashboard import _is_local_demo_host
    request = Request({'type': 'http', 'method': 'GET', 'path': '/', 'scheme': 'http',
        'query_string': b'', 'client': ('198.51.100.10', 1234), 'server': ('test', 80),
        'headers': [(b'host', b'localhost.example.test')]})
    assert not _is_local_demo_host(request)


def test_email_lab_never_discloses_configured_owner_key(monkeypatch):
    from src.app.routers.merchant_dashboard import merchant_email_lab
    from fastapi import HTTPException
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('OWNER_API_KEY', 'synthetic-secret-never-real')
    request = Request({'type': 'http', 'method': 'GET', 'path': '/merchant/email-lab', 'scheme': 'http',
        'query_string': b'', 'client': ('127.0.0.1', 1234), 'server': ('test', 80), 'headers': []})
    try:
        response = merchant_email_lab(request)
    except HTTPException as exc:
        assert exc.status_code in (403, 404)
        return
    assert 'synthetic-secret-never-real' not in str(response.raw_headers)
    assert b'synthetic-secret-never-real' not in response.body
