"""Credentials cannot advertise a native payment integration that cannot load."""
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def configured(monkeypatch):
    from src.app.routers import payments
    from src.app.services import checkout_readiness

    settings = SimpleNamespace(app_env='test', stripe_api_key='sk_test_owned',
                               paypal_client_id='owned', paypal_client_secret='owned-secret')
    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED', '1')
    monkeypatch.setenv('ALLOW_DEMO_CHECKOUT', '0')
    monkeypatch.setenv('STRIPE_PUBLISHABLE_KEY', 'pk_test_owned')
    monkeypatch.setattr(checkout_readiness, 'get_settings', lambda: settings)
    monkeypatch.setattr(checkout_readiness, 'shipping_readiness', lambda: {'ready': False, 'reason': 'Owned'})
    monkeypatch.setattr(payments, 'get_settings', lambda: settings)
    monkeypatch.setattr(payments, '_ff_get_flags', lambda: {'CAPABILITIES': {
        provider: {'enabled': True} for provider in ('stripe', 'paypal', 'revolut', 'googlepay', 'afterpay')}})
    return payments, checkout_readiness


def stripe_interface(monkeypatch):
    module = ModuleType('stripe')
    module.PaymentIntent = SimpleNamespace(create=lambda **kwargs: pytest.fail('Readiness called a provider'))
    module.Refund = SimpleNamespace(create=lambda **kwargs: pytest.fail('Readiness called a provider'))
    monkeypatch.setitem(sys.modules, 'stripe', module)


@pytest.mark.parametrize('surface', ['buyer', 'stripe', 'paypal'])
def test_absent_native_sdk_cannot_report_configured_payment(configured, monkeypatch, surface):
    payments, checkout = configured
    for name in ('stripe', 'paypalcheckoutsdk', 'paypalcheckoutsdk.core', 'paypalcheckoutsdk.orders'):
        monkeypatch.setitem(sys.modules, name, None)
    if surface == 'buyer':
        readiness = checkout.buyer_checkout_readiness()['payment']
        assert readiness['status'] == 'unavailable' and readiness['real_payment'] is False
        assert readiness['methods'] == []
        assert 'sk_test_owned' not in str(readiness) and 'sdk' not in str(readiness).lower()
    else:
        readiness = payments.providers_rollout_status(role='owner')
        row = next(row for row in readiness['providers'] if row['provider'] == surface)
        assert row['real_integration_ready'] is False
        assert row['rollout_stage'] == 'disabled'
        assert readiness['provider_concentration_risk'] == 'high'


def test_importable_sdk_without_required_interface_is_unavailable(configured, monkeypatch):
    _, checkout = configured
    monkeypatch.setitem(sys.modules, 'stripe', ModuleType('stripe'))
    assert checkout.buyer_checkout_readiness()['payment']['real_payment'] is False


def test_broken_sdk_initialization_is_unavailable_without_leaking_error(configured, monkeypatch):
    _, checkout = configured
    module = ModuleType('stripe')

    def broken(name):
        raise RuntimeError('private-sdk-error-and-secret')

    module.__getattr__ = broken
    monkeypatch.setitem(sys.modules, 'stripe', module)
    readiness = checkout.buyer_checkout_readiness()['payment']
    assert readiness['real_payment'] is False
    assert 'private-sdk-error-and-secret' not in str(readiness)


@pytest.mark.parametrize('setting', ['invalid', '2', 'enabled'])
def test_buyer_readiness_uses_the_same_invalid_policy_denial_as_dispatch(configured, monkeypatch, setting):
    _, checkout = configured
    stripe_interface(monkeypatch)
    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED', setting)
    assert checkout.buyer_checkout_readiness()['payment']['real_payment'] is False


def test_usable_local_sdk_interface_preserves_configured_checkout_without_provider_calls(configured, monkeypatch):
    _, checkout = configured
    stripe_interface(monkeypatch)
    readiness = checkout.buyer_checkout_readiness()['payment']
    assert readiness['status'] == 'configured'
    assert readiness['methods'] == ['stripe']
    assert readiness['real_payment'] is True


@pytest.mark.parametrize('complete', [False, True])
def test_paypal_local_sdk_interfaces_control_reported_capability(configured, monkeypatch, complete):
    payments, _ = configured
    core, orders = ModuleType('paypalcheckoutsdk.core'), ModuleType('paypalcheckoutsdk.orders')
    core.SandboxEnvironment = lambda *args: pytest.fail('Readiness instantiated a provider')
    if complete:
        core.PayPalHttpClient = lambda *args: pytest.fail('Readiness instantiated a provider')
    orders.OrdersCreateRequest = lambda *args: pytest.fail('Readiness instantiated a provider')
    monkeypatch.setitem(sys.modules, 'paypalcheckoutsdk.core', core)
    monkeypatch.setitem(sys.modules, 'paypalcheckoutsdk.orders', orders)
    report = payments.providers_rollout_status(role='owner')
    row = next(row for row in report['providers'] if row['provider'] == 'paypal')
    assert row['real_integration_ready'] is complete
    assert row['rollout_stage'] == ('beta' if complete else 'disabled')
