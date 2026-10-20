from types import SimpleNamespace
import importlib
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.utils import default_headers


def _adapter_request(monkeypatch, provider, enabled, *, revoke_at_dispatch=False):
    module = importlib.import_module('src.app.routers.payments_' + provider)
    from src.app.routers import payments
    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED', '1' if enabled else '0')
    monkeypatch.setattr(module, '_ff_get_flags', lambda: {'CAPABILITIES': {provider: {'enabled': True}}})
    monkeypatch.setattr(module, 'evaluate_transaction_firewall', lambda **kwargs: {'action': 'allow'})
    monkeypatch.setattr(module, 'get_settings', lambda: SimpleNamespace(
        app_env='test', paypal_client_id='synthetic', paypal_client_secret='synthetic'))
    calls, dedup = [], []
    monkeypatch.setattr(payments, '_idempotent', lambda *args, **kwargs: dedup.append(args) or True)
    if provider == 'paypal':
        class FakePayPal:
            def __init__(self, *args):
                if revoke_at_dispatch:
                    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED', '0')
            def create_order(self, **kwargs):
                if revoke_at_dispatch:
                    from src.app.services.payment_execution_policy import require_payment_execution
                    require_payment_execution()
                calls.append(kwargs)
                return {'id': 'intent_synthetic', 'status': 'created'}
        monkeypatch.setattr(module, 'PayPalClient', FakePayPal)
    else:
        monkeypatch.setenv(provider.upper() + '_API_BASE_URL', 'https://provider.invalid')
        monkeypatch.setenv(provider.upper() + '_API_KEY', 'synthetic-only')
        class FakeHTTP:
            def __init__(self, **kwargs):
                pass
            def __enter__(self):
                if revoke_at_dispatch:
                    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED', '0')
                return self
            def __exit__(self, *args):
                pass
            def post(self, *args, **kwargs):
                calls.append(kwargs)
                return SimpleNamespace(status_code=200, content=b'{}',
                    json=lambda: {'id': 'intent_synthetic', 'status': 'created'})
        monkeypatch.setattr(module.httpx, 'Client', FakeHTTP)
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app, headers=default_headers()) as client:
        response = client.post(f'/api/v1/payments/{provider}/intent', params={
            'uid': 'synthetic-buyer', 'amount_cents': 100, 'idempotency_key': 'synthetic-key'})
    return response, calls, dedup


@pytest.mark.parametrize('provider', ['paypal', 'revolut', 'googlepay', 'afterpay'])
@pytest.mark.parametrize('enabled', [False, True])
def test_adapter_policy_precedes_dedup_and_provider_effect(monkeypatch, provider, enabled):
    response, calls, dedup = _adapter_request(monkeypatch, provider, enabled)
    assert response.status_code == (200 if enabled else 503), response.text
    assert len(calls) == (1 if enabled else 0)
    if not enabled:
        assert dedup == [], 'disabled execution must not consume a retry key'


@pytest.mark.parametrize('provider', ['paypal', 'revolut', 'googlepay', 'afterpay'])
def test_revocation_at_provider_dispatch_reports_policy_denial(monkeypatch, provider):
    response, calls, _ = _adapter_request(monkeypatch, provider, True, revoke_at_dispatch=True)
    assert response.status_code == 503, response.text
    assert calls == []
