from types import SimpleNamespace
import pytest
from src.app.services.payments import StripeClient
from src.app.services.payments import PayPalClient


@pytest.mark.parametrize('method',['create_refund','create_payment_intent'])
@pytest.mark.parametrize('enabled',[False,True])
def test_provider_boundary_honors_execution_policy_before_sdk_calls(monkeypatch,method,enabled):
    from src.app import config
    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED','1' if enabled else '0')
    monkeypatch.setattr(config,'get_settings',lambda:SimpleNamespace(app_env='local'))
    calls=[]
    def provider(**kwargs):
        calls.append(kwargs)
        return {'id':'re_fixture','status':'succeeded','amount':100,'currency':'AUD'}
    client=object.__new__(StripeClient)
    client.stripe=SimpleNamespace(Refund=SimpleNamespace(create=provider),PaymentIntent=SimpleNamespace(create=provider))
    client.supply_chain=SimpleNamespace(check_endpoint_integrity=lambda *_:None,detect_response_anomaly=lambda *_:None)
    kwargs={'payment_intent_id':'pi_fixture','amount_cents':100} if method=='create_refund' else {'amount_cents':100}
    if enabled:
        getattr(client,method)(**kwargs)
        assert len(calls)==1
    else:
        with pytest.raises(RuntimeError,match='payment_execution_disabled'):
            getattr(client,method)(**kwargs)
        assert calls==[]


@pytest.mark.parametrize('enabled', [False, True])
def test_paypal_boundary_honors_policy_before_sdk_execute(monkeypatch, enabled):
    from src.app import config
    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED', '1' if enabled else '0')
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(app_env='test'))
    calls = []
    client = object.__new__(PayPalClient)
    client.supply_chain = SimpleNamespace(check_endpoint_integrity=lambda *args: None,
                                         detect_response_anomaly=lambda *args: None)
    client.OrdersCreateRequest = lambda: SimpleNamespace(prefer=lambda *args: None,
                                                       request_body=lambda *args: None)
    def execute(request):
        calls.append(request)
        return SimpleNamespace(result=SimpleNamespace(id='synthetic', status='created'))
    client.client = SimpleNamespace(execute=execute)
    if enabled:
        client.create_order(100)
        assert len(calls) == 1
    else:
        with pytest.raises(RuntimeError, match='payment_execution_disabled'):
            client.create_order(100)
        assert calls == []


@pytest.mark.parametrize('method', ['create_refund', 'create_payment_intent'])
def test_stripe_rechecks_policy_after_pre_dispatch_work(monkeypatch, method):
    from src.app import config
    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED', '1')
    monkeypatch.setattr(config, 'get_settings', lambda: SimpleNamespace(app_env='test'))
    calls = []

    def revoke(*args):
        monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED', '0')

    def provider(**kwargs):
        calls.append(kwargs)
        return {'id': 're_owned', 'status': 'succeeded'}

    client = object.__new__(StripeClient)
    client.stripe = SimpleNamespace(Refund=SimpleNamespace(create=provider),
                                   PaymentIntent=SimpleNamespace(create=provider))
    client.supply_chain = SimpleNamespace(check_endpoint_integrity=revoke,
                                         detect_response_anomaly=lambda *args: None)
    kwargs = ({'payment_intent_id': 'pi_owned', 'amount_cents': 100}
              if method == 'create_refund' else {'amount_cents': 100})
    with pytest.raises(RuntimeError, match='payment_execution_disabled'):
        getattr(client, method)(**kwargs)
    assert calls == []


@pytest.mark.parametrize('setting', ['invalid', '2', 'enabled'])
def test_invalid_execution_setting_cannot_enable_payment_effects(monkeypatch, setting):
    from src.app.services.payment_execution_policy import payment_execution_enabled
    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED', setting)
    assert payment_execution_enabled('test') is False


@pytest.mark.parametrize('environment,expected', [
    ('local', True), ('development', True), ('test', True),
    ('production', False), ('staging', False), ('unknown', False), ('', False)])
def test_unset_execution_setting_uses_explicit_environment(monkeypatch, environment, expected):
    from src.app.services.payment_execution_policy import payment_execution_enabled
    monkeypatch.delenv('PAYMENT_EXECUTION_ENABLED', raising=False)
    assert payment_execution_enabled(environment) is expected
