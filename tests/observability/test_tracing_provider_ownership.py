from types import SimpleNamespace


def _fresh_app():
    # Lifecycle ownership needs the real factory, not the shared pytest app.
    import src.app.main as main
    return getattr(main, "_original_create_app", main.create_app)()


def _fake_runtime(monkeypatch, *, initialized=False):
    from src.app.observability import init as telemetry
    class Proxy:
        pass
    providers, exporters, processors = [], [], []
    class Provider:
        def __init__(self, **kwargs):
            providers.append(self)
        def add_span_processor(self, processor):
            pass
        def shutdown(self):
            pass
    current = [object() if initialized else Proxy()]
    def install(provider):
        if isinstance(current[0], Proxy):
            current[0] = provider
    def exporter(**kwargs):
        exporters.append(kwargs)
        return object()
    def processor(value):
        processors.append(value)
        return object()
    monkeypatch.setattr(telemetry, 'trace', SimpleNamespace(
        ProxyTracerProvider=Proxy, get_tracer_provider=lambda: current[0],
        set_tracer_provider=install))
    monkeypatch.setattr(telemetry, 'TracerProvider', Provider)
    monkeypatch.setattr(telemetry, 'Resource', SimpleNamespace(create=lambda value: object()))
    monkeypatch.setattr(telemetry, 'JaegerExporter', exporter)
    monkeypatch.setattr(telemetry, 'BatchSpanProcessor', processor)
    monkeypatch.setenv('JAEGER_ENABLED', '1')
    monkeypatch.delenv('OTEL_EXPORTER_OTLP_ENDPOINT', raising=False)
    monkeypatch.delenv('OTLP_ENDPOINT', raising=False)
    return telemetry, providers, exporters, processors


def test_repeated_app_initialization_does_not_create_unused_exporters(monkeypatch):
    telemetry, providers, exporters, processors = _fake_runtime(monkeypatch)
    for _ in range(3):
        telemetry.init_tracing()
    assert len(providers) == len(exporters) == len(processors) == 1


def test_existing_process_provider_is_respected_without_allocating_workers(monkeypatch):
    telemetry, providers, exporters, processors = _fake_runtime(monkeypatch, initialized=True)
    telemetry.init_tracing()
    assert providers == exporters == processors == []


def test_app_shutdown_flushes_but_does_not_shutdown_shared_process_provider(monkeypatch):
    import asyncio
    from src.app.main import create_app
    from opentelemetry import trace
    calls = []
    provider = SimpleNamespace(shutdown=lambda: calls.append('shutdown'),
                               force_flush=lambda **kwargs: calls.append('flush'))
    monkeypatch.setattr(trace, 'get_tracer_provider', lambda: provider)
    app = _fresh_app()
    shutdown = next(handler for handler in app.router.on_shutdown
                    if handler.__name__ == '_on_shutdown')
    asyncio.run(shutdown())
    assert calls == ['flush']


def test_lost_registration_closes_unused_provider_before_exporter_allocation(monkeypatch):
    telemetry, providers, exporters, processors = _fake_runtime(monkeypatch)
    closed = []
    monkeypatch.setattr(telemetry.TracerProvider, 'shutdown', lambda provider: closed.append(provider))
    other = object()
    def lose_registration(provider):
        monkeypatch.setattr(telemetry.trace, 'get_tracer_provider', lambda: other)
    monkeypatch.setattr(telemetry.trace, 'set_tracer_provider', lose_registration)
    telemetry.init_tracing()
    assert len(providers) == 1 and closed == providers
    assert exporters == processors == []


def test_legacy_tracing_initializer_respects_existing_process_provider(monkeypatch):
    telemetry, providers, exporters, processors = _fake_runtime(monkeypatch, initialized=True)
    from src.app.observability import tracing
    monkeypatch.setattr(tracing, '_initialized', False)
    monkeypatch.setattr(tracing, 'trace', telemetry.trace)
    monkeypatch.setattr(tracing, 'TracerProvider', telemetry.TracerProvider)
    monkeypatch.setattr(tracing, 'Resource', telemetry.Resource)
    monkeypatch.setenv('DISABLE_TRACING', '1')
    tracing.init_tracer()
    assert providers == exporters == processors == []


def test_actual_asgi_lifespan_flushes_shared_tracing(monkeypatch):
    import asyncio
    from opentelemetry import trace
    from src.app.main import create_app
    class Provider(trace.NoOpTracerProvider):
        def force_flush(self, **kwargs):
            calls.append('flush')
        def shutdown(self):
            calls.append('shutdown')
    calls = []
    monkeypatch.setattr(trace, 'get_tracer_provider', lambda: Provider())
    app = _fresh_app()
    async def cycle():
        async with app.router.lifespan_context(app):
            pass
    asyncio.run(cycle())
    assert calls == ['flush']


def test_required_startup_failure_disposes_owned_database_engine(monkeypatch, tmp_path):
    import asyncio
    import pytest
    import src.app.main as main
    import src.app.models.db as dbmod
    original_engine = dbmod.engine
    monkeypatch.setattr(dbmod, 'engine', None)
    monkeypatch.setenv('DATABASE_URL', f'sqlite+pysqlite:///{tmp_path}/startup_failure.sqlite3')
    app = _fresh_app()
    disposed = []
    engine = app.state.engine
    original_dispose = engine.dispose
    def dispose():
        disposed.append(True)
        original_dispose()
    monkeypatch.setattr(engine, 'dispose', dispose)
    def fail_startup(*args, **kwargs):
        raise RuntimeError('required_startup_failed')
    monkeypatch.setattr(main, 'run_startup_step', fail_startup)
    async def cycle():
        with pytest.raises(RuntimeError, match='required_startup_failed'):
            async with app.router.lifespan_context(app):
                pass
    try:
        asyncio.run(cycle())
        assert disposed == [True]
    finally:
        dbmod.set_engine(original_engine)


def test_actual_asgi_shutdown_preserves_borrowed_engine(monkeypatch):
    import asyncio
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool
    from src.app.main import create_app
    import src.app.models.db as dbmod
    original_engine = dbmod.engine
    engine = create_engine('sqlite+pysqlite:///:memory:', poolclass=StaticPool,
                           connect_args={'check_same_thread': False})
    with engine.begin() as db:
        db.execute(text('CREATE TABLE cleanup_probe (value INTEGER)'))
        db.execute(text('INSERT INTO cleanup_probe VALUES (1)'))
    dbmod.set_engine(engine)
    app = _fresh_app()
    assert app.state.engine is engine
    assert app.state.owns_engine is False
    disposed = []
    original_dispose = engine.dispose
    def track_dispose():
        disposed.append(True)
        original_dispose()
    monkeypatch.setattr(engine, "dispose", track_dispose)
    async def cycle():
        async with app.router.lifespan_context(app):
            pass
    try:
        asyncio.run(cycle())
        assert disposed == [], "an app must not dispose a borrowed engine"
        with engine.connect() as db:
            assert db.execute(text('SELECT value FROM cleanup_probe')).scalar() == 1
    finally:
        dbmod.set_engine(original_engine)
        engine.dispose()
