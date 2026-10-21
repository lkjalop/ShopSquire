from scripts.roadmap_runtime import simulation_controls


def test_isolated_effect_controls_override_inherited_live_settings(monkeypatch):
    import os
    monkeypatch.setenv('FULFILLMENT_PO_TRANSPORT','erp')
    monkeypatch.setenv('PAYMENT_EXECUTION_ENABLED','1')
    monkeypatch.setenv('STRIPE_API_KEY','synthetic-secret-sentinel')
    env={**os.environ,**simulation_controls()}
    assert env['FULFILLMENT_PO_TRANSPORT']=='sandbox'
    assert env['FULFILLMENT_SUPPLIER_TRANSPORT']=='sandbox'
    assert env['PAYMENT_EXECUTION_ENABLED']=='0'
    assert env['STRIPE_API_KEY']==env['STRIPE_API_KEY_REF']==env['ERP_PO_URL']==''


def test_local_browser_does_not_inherit_cache_or_queue_credentials(monkeypatch):
    import os
    from scripts.roadmap_runtime import local_backend_isolation
    monkeypatch.setenv('REDIS_URL', 'redis://synthetic-sentinel@shared-cache:6379/0')
    monkeypatch.setenv('REDIS_URL_REF', 'vault:synthetic-sentinel')
    monkeypatch.setenv('CELERY_BROKER_URL', 'redis://shared-broker:6379/0')
    env = {**os.environ, **local_backend_isolation()}
    assert env['REDIS_URL'] == env['CELERY_BROKER_URL'] == 'redis://127.0.0.1:1/0'
    assert env['REDIS_URL_REF'] == env['REDIS_ACL_PASSWORD'] == ''
    assert env['TASK_CONSUMER_ENABLED'] == '0'
