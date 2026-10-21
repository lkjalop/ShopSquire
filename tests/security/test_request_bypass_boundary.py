"""Untrusted request headers cannot disable runtime admission or observation."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from tests.security.test_observer_session_ownership import observer_database


@pytest.fixture
def guarded_app(tmp_path, monkeypatch):
    import src.app.main as main
    from src.app.models import db as database
    from src.app.security import anomaly_detector

    monkeypatch.setenv('APP_ENV', 'test')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:///' + str(tmp_path / 'guard.sqlite3'))
    monkeypatch.setenv('DISABLE_TRACING', '1')
    monkeypatch.setenv('OTEL_SDK_DISABLED', 'true')
    monkeypatch.setenv('OBSERVER_THREADED', '0')
    monkeypatch.setenv('ALLOW_TEST_REQUEST_BYPASS', '0')
    monkeypatch.setenv('SKIP_OBSERVER_ENDPOINTS', '')
    engine = create_engine('sqlite:///' + str(tmp_path / 'guard.sqlite3'))
    monkeypatch.setattr(database, 'engine', engine)
    factory = getattr(main, '_original_create_app', main.create_app)
    app = factory()
    app.state.engine = engine
    app.state.max_concurrency = 0
    app.state.rate_limit_per_min = 0
    app.state.chaos_error_prob = 0
    events = []
    monkeypatch.setattr(main, 'emit_security_event', lambda path, *args, **kw: events.append(path))
    monkeypatch.setattr(anomaly_detector, 'detect_anomaly', lambda payload: None)

    @app.get('/__request-guard/probe')
    def probe():
        return {'accepted': True}

    with TestClient(app, base_url='http://127.0.0.1', raise_server_exceptions=False) as client:
        yield app, client, events
    engine.dispose()


@pytest.mark.parametrize('environment,enabled,bypass', [
    ('prod', '0', False), ('prod', '1', False),
    ('production', '1', False), ('staging', '1', False),
    ('local', '1', False), ('test', '0', False), ('test', '', False),
    ('test', 'false', False), ('test', '1', True),
])
def test_skip_header_cannot_suppress_observation_outside_explicit_test_mode(
    guarded_app, monkeypatch, environment, enabled, bypass,
):
    _, client, events = guarded_app
    monkeypatch.setenv('APP_ENV', environment)
    monkeypatch.setenv('ALLOW_TEST_REQUEST_BYPASS', enabled)
    response = client.get('/__request-guard/probe', headers={'x-skip-observer': '1'})
    assert response.status_code == 200
    assert events == ([] if bypass else ['/__request-guard/probe'])


@pytest.mark.parametrize('environment,enabled,bypass', [
    ('production', '1', False), ('local', '1', False),
    ('test', '0', False), ('test', '1', True),
])
def test_skip_header_cannot_disable_ip_admission(
    guarded_app, monkeypatch, environment, enabled, bypass,
):
    app, client, _ = guarded_app
    monkeypatch.setenv('APP_ENV', environment)
    monkeypatch.setenv('ALLOW_TEST_REQUEST_BYPASS', enabled)
    app.state.rate_limit_per_min = 1
    statuses = [client.get('/__request-guard/probe', headers={'x-skip-observer': '1'}).status_code
                for _ in range(2)]
    assert statuses == ([200, 200] if bypass else [200, 429])


@pytest.mark.parametrize('environment,enabled,bypass', [
    ('production', '1', False), ('local', '1', False),
    ('test', '0', False), ('test', '1', True),
])
def test_test_endpoint_skip_list_does_not_disable_production_observation(
    guarded_app, monkeypatch, environment, enabled, bypass,
):
    _, client, events = guarded_app
    monkeypatch.setenv('APP_ENV', environment)
    monkeypatch.setenv('ALLOW_TEST_REQUEST_BYPASS', enabled)
    monkeypatch.setenv('SKIP_OBSERVER_ENDPOINTS', '/__request-guard')
    assert client.get('/__request-guard/probe').status_code == 200
    assert events == ([] if bypass else ['/__request-guard/probe'])


@pytest.mark.parametrize('environment,enabled,bypass', [
    ('production', '1', False), ('test', '0', False), ('test', '1', True),
])
def test_skip_header_does_not_silence_configured_chaos_outside_explicit_test_mode(
    guarded_app, monkeypatch, environment, enabled, bypass,
):
    app, client, _ = guarded_app
    monkeypatch.setenv('APP_ENV', environment)
    monkeypatch.setenv('ALLOW_TEST_REQUEST_BYPASS', enabled)
    app.state.chaos_error_prob = 1
    response = client.get('/__request-guard/probe', headers={'x-skip-observer': '1'})
    assert response.status_code == (200 if bypass else 500)


def test_enabling_test_bypass_does_not_skip_requests_without_the_header(guarded_app, monkeypatch):
    app, client, events = guarded_app
    monkeypatch.setenv('ALLOW_TEST_REQUEST_BYPASS', '1')
    app.state.rate_limit_per_min = 1
    assert client.get('/__request-guard/probe').status_code == 200
    assert client.get('/__request-guard/probe').status_code == 429
    assert events


@pytest.mark.parametrize('environment,enabled,bypass', [
    ('production', '1', False), ('local', '1', False),
    ('test', '0', False), ('test', '1', True),
])
def test_direct_security_emission_is_durable_despite_a_test_skip_list(
    observer_database, monkeypatch, environment, enabled, bypass,
):
    from types import SimpleNamespace
    from starlette.requests import Request
    from sqlalchemy import text
    from src.app.security import observer

    monkeypatch.setenv('APP_ENV', environment)
    monkeypatch.setenv('ALLOW_TEST_REQUEST_BYPASS', enabled)
    monkeypatch.setenv('SKIP_OBSERVER_ENDPOINTS', '/__direct-guard')
    request = Request({'type': 'http', 'app': SimpleNamespace(state=SimpleNamespace(engine=observer_database)),
                       'state': {}, 'headers': [], 'client': ('127.0.0.1', 1)})
    observer.emit_security_event('/__direct-guard', {'analysis': {'severity': 'info', 'risk_adj': 0}}, request=request)
    with observer_database.connect() as db:
        assert db.scalar(text('SELECT count(*) FROM security_events')) == (0 if bypass else 1)


@pytest.mark.parametrize('environment,enabled,bypass', [
    ('production', '1', False), ('local', '1', False),
    ('test', '0', False), ('test', '1', True),
])
def test_durable_decision_trace_survives_a_test_skip_list(
    guarded_app, monkeypatch, environment, enabled, bypass,
):
    import uuid
    from sqlalchemy import text
    from src.app.models.database_ownership import database_owner
    from src.app.services import decision_log

    app, _, _ = guarded_app
    monkeypatch.setenv('APP_ENV', environment)
    monkeypatch.setenv('ALLOW_TEST_REQUEST_BYPASS', enabled)
    monkeypatch.setenv('SKIP_OBSERVER_ENDPOINTS', '/api/v1/recommend')
    monkeypatch.setattr(decision_log, '_TRACE_TABLE_ENSURED', False)
    trace_id = str(uuid.uuid4())
    with database_owner(app.state.engine):
        decision_log.log_trace_event(trace_id, 'agent_process', 'system', 'guard-test',
                                     'system', None, {'test': 'durable-boundary'})
    with app.state.engine.connect() as db:
        assert db.scalar(text('SELECT count(*) FROM decision_trace_events WHERE trace_id=:id'),
                         {'id': trace_id}) == (0 if bypass else 1)
