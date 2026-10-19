import gc
import weakref

from fastapi import FastAPI

from src.app.observability import init as observability


def test_instrumentation_does_not_keep_discarded_apps_alive(monkeypatch):
    monkeypatch.setenv('DISABLE_TRACING', '0')
    monkeypatch.setenv('OTEL_SDK_DISABLED', 'false')
    monkeypatch.setattr(observability, 'init_tracing', lambda **kwargs: None)
    app = FastAPI()
    ref = weakref.ref(app)
    observability.instrument_app(app)
    del app
    gc.collect()
    assert ref() is None, 'tracing bookkeeping must not own the application lifecycle'


def test_explicitly_disabled_tracing_still_exposes_metrics(monkeypatch):
    monkeypatch.setenv('DISABLE_TRACING', '1')
    calls = []
    monkeypatch.setattr(observability, 'init_tracing', lambda **kwargs: calls.append('tracer'))
    app = FastAPI()
    observability.instrument_app(app)
    assert calls == []
    assert not getattr(app, '_is_instrumented_by_opentelemetry', False)
    assert any(route.path == '/metrics' for route in app.routes)
