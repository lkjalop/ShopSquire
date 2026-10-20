"""Closed app factories must not stay alive through cached endpoint callables."""
import gc
import weakref

from fastapi.testclient import TestClient


def test_closed_application_is_collectable_after_public_probes(monkeypatch):
    import src.app.main as main
    monkeypatch.setenv('DISABLE_TRACING', '1')
    monkeypatch.setenv('OTEL_SDK_DISABLED', 'true')
    monkeypatch.setenv('CV_OCR_PROVIDER', 'disabled')
    monkeypatch.setenv('TEST_FAST_HEALTH', '1')
    monkeypatch.setenv('INVENTORY_WORKER_ENABLED', '0')
    monkeypatch.setenv('VLM_WARMUP_ON_START', '0')
    factory = getattr(main, '_original_create_app', main.create_app)
    application = factory()
    reference = weakref.ref(application)
    with TestClient(application) as client:
        assert client.get('/health').status_code == 200
        assert client.get('/status/summary').status_code == 200
        assert client.get('/api/v1/status/summary').status_code == 200
        readiness = client.get('/readyz')
        assert readiness.status_code in {200, 503}
        assert isinstance(readiness.json(), dict)
    del readiness, client, application
    gc.collect()
    assert reference() is None, 'closed app retained by its cached endpoint closure'


def test_health_reads_the_application_serving_the_request(monkeypatch):
    import src.app.main as main
    monkeypatch.setenv('DISABLE_TRACING', '1')
    monkeypatch.setenv('OTEL_SDK_DISABLED', 'true')
    monkeypatch.setenv('TEST_FAST_HEALTH', '1')
    monkeypatch.setenv('INVENTORY_WORKER_ENABLED', '0')
    monkeypatch.setenv('VLM_WARMUP_ON_START', '0')
    factory = getattr(main, '_original_create_app', main.create_app)
    first, second = factory(), factory()
    with TestClient(first) as first_client, TestClient(second) as second_client:
        first.state.startup_capabilities = {'first-owner': {'ready': True}}
        second.state.startup_capabilities = {'second-owner': {'ready': True}}
        assert first_client.get('/health').json()['startup_capabilities'] == {'first-owner': {'ready': True}}
        assert second_client.get('/health').json()['startup_capabilities'] == {'second-owner': {'ready': True}}
        assert first_client.get('/health').json()['startup_capabilities'] == {'first-owner': {'ready': True}}
