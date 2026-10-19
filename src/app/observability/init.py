from typing import Optional
import os
import threading
import weakref

from fastapi import FastAPI

# OpenTelemetry (optional in minimal dev/test installs)
try:  # pragma: no cover
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except Exception:  # pragma: no cover
    trace = None  # type: ignore
    Resource = None  # type: ignore
    TracerProvider = None  # type: ignore
    BatchSpanProcessor = None  # type: ignore

try:  # pragma: no cover
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter  # type: ignore
except Exception:  # pragma: no cover
    JaegerExporter = None  # type: ignore
try:  # pragma: no cover
    # Prefer OTLP if available and configured
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore
except Exception:  # pragma: no cover
    OTLPSpanExporter = None  # type: ignore

try:  # pragma: no cover
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore
    from opentelemetry.instrumentation.requests import RequestsInstrumentor  # type: ignore
except Exception:  # pragma: no cover
    FastAPIInstrumentor = None  # type: ignore
    RequestsInstrumentor = None  # type: ignore

# Prometheus
from prometheus_client import make_asgi_app, Counter, Summary


REQUEST_COUNT = Counter("http_requests_total", "Total HTTP Requests", ["method", "path", "status"])
REQUEST_LATENCY = Summary("http_request_latency_seconds", "HTTP request latency seconds")
_TRACING_INIT_LOCK = threading.Lock()
_APP_REGISTRY_LOCK = threading.Lock()


def _non_owning_fastapi_registry() -> None:
    """Keep older OpenTelemetry bookkeeping from retaining every app forever.

    The installed instrumentor uses a strong set, including for manual
    instrument_app calls. Its __del__ cleanup cannot run while that set owns
    the app. WeakSet preserves the registry API and live-app instrumentation.
    Already corrected instrumentor versions need no adaptation.
    """
    from opentelemetry.instrumentation import fastapi as instrumentation
    instrumented_type = getattr(instrumentation, '_InstrumentedFastAPI', None)
    with _APP_REGISTRY_LOCK:
        registry = getattr(instrumented_type, '_instrumented_fastapi_apps', None)
        if isinstance(registry, set):
            instrumented_type._instrumented_fastapi_apps = weakref.WeakSet(registry)


def init_tracing(service_name: str = "shopsquire") -> None:
    # Configure tracer provider and OTLP/Jaeger exporter if available.
    if trace is None or TracerProvider is None or Resource is None or BatchSpanProcessor is None:
        return
    with _TRACING_INIT_LOCK:
        # OpenTelemetry owns one process-global provider. A provider rejected
        # by set_tracer_provider must never acquire unused exporter workers.
        if not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider):
            return
        _configure_process_tracing(service_name)


def _configure_process_tracing(service_name: str) -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    trace.set_tracer_provider(provider)
    if trace.get_tracer_provider() is not provider:
        provider.shutdown()
        return
    # OTLP HTTP endpoint takes precedence if set
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTLP_ENDPOINT")
    try:
        if OTLPSpanExporter is not None and otlp_endpoint:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint.rstrip("/"))
            provider.add_span_processor(BatchSpanProcessor(exporter))
            return
    except Exception:
        pass
    # Fallback to Jaeger agent exporter only if explicitly enabled
    use_jaeger = os.getenv("JAEGER_ENABLED", "0").lower() in ("1", "true", "yes")
    jaeger_host = os.getenv("JAEGER_HOST") or os.getenv("OTEL_EXPORTER_JAEGER_AGENT_HOST")
    jaeger_port = int(os.getenv("JAEGER_PORT") or os.getenv("OTEL_EXPORTER_JAEGER_AGENT_PORT") or 6831)
    try:
        if use_jaeger and JaegerExporter is not None and (jaeger_host or jaeger_port):
            exporter = JaegerExporter(agent_host_name=jaeger_host, agent_port=jaeger_port)
            provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception:
        # best-effort: continue without exporter
        pass


def init_metrics(app: FastAPI) -> None:
    # Mount Prometheus metrics at /metrics
    try:
        prometheus_app = make_asgi_app()
        app.mount("/metrics", prometheus_app)
    except Exception:
        pass


def instrument_app(app: FastAPI, service_name: Optional[str] = None) -> None:
    disabled = any(str(os.getenv(name, '')).strip().lower() in {'1', 'true', 'yes', 'on'}
                   for name in ('DISABLE_TRACING', 'OTEL_SDK_DISABLED'))
    try:
        if service_name is None:
            service_name = os.getenv("SERVICE_NAME") or "shopsquire"
        if not disabled:
            init_tracing(service_name=service_name)
        if not disabled and FastAPIInstrumentor is not None:
            _non_owning_fastapi_registry()
            FastAPIInstrumentor.instrument_app(app)
        if not disabled and RequestsInstrumentor is not None:
            instrumentor = RequestsInstrumentor()
            if not instrumentor.is_instrumented_by_opentelemetry:
                instrumentor.instrument()
    except Exception:
        pass
    try:
        init_metrics(app)
    except Exception:
        pass


# Simple helpers for recording metrics in code paths
def record_request(method: str, path: str, status: str, latency_seconds: float):
    try:
        REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
        REQUEST_LATENCY.observe(latency_seconds)
    except Exception:
        pass
