import os
import logging
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter


_initialized = False
_logger = logging.getLogger("shopsquire.observability.tracing")


def init_tracer(service_name: str = "shopsquire-api", app=None) -> None:
    global _initialized
    if _initialized:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    # Allow disabling tracing to avoid noisy test warnings
    disable = os.getenv("DISABLE_TRACING", "0").lower() in ("1", "true", "yes")
    if not disable:
        processor = None

        # Prefer OTLP exporter if OTEL endpoint is configured
        otel_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINTS")
        if otel_endpoint:
            try:
                # Try gRPC OTLP exporter first
                try:
                    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

                    exporter = OTLPSpanExporter(endpoint=otel_endpoint)
                    processor = BatchSpanProcessor(exporter)
                    _logger.info("OTel: using OTLP gRPC exporter -> %s", otel_endpoint)
                except Exception:
                    # Fallback to HTTP/proto exporter
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as OTLPHTTP

                    exporter = OTLPHTTP(endpoint=otel_endpoint)
                    processor = BatchSpanProcessor(exporter)
                    _logger.info("OTel: using OTLP HTTP exporter -> %s", otel_endpoint)
            except Exception as exc:
                _logger.warning("OTel: failed to initialize OTLP exporter (%s), falling back: %s", otel_endpoint, exc)

        # Next, prefer Jaeger only if explicitly enabled and OTLP not used
        if processor is None:
            # Default to disabled to avoid deprecation warnings in dev/test
            use_jaeger = os.getenv("JAEGER_ENABLED", "0").lower() in ("1", "true", "yes")
            if use_jaeger:
                jaeger_host = os.getenv("JAEGER_HOST", "jaeger")
                jaeger_port = int(os.getenv("JAEGER_PORT", "6831"))
                try:
                    from opentelemetry.exporter.jaeger.thrift import JaegerExporter

                    exporter = JaegerExporter(agent_host_name=jaeger_host, agent_port=jaeger_port)
                    processor = BatchSpanProcessor(exporter)
                    _logger.info("OTel: using Jaeger exporter -> %s:%s", jaeger_host, jaeger_port)
                except Exception as exc:
                    _logger.warning("OTel: failed to initialize Jaeger exporter: %s", exc)

        # Final fallback: console exporter for local dev/tests
        if processor is None:
            processor = BatchSpanProcessor(ConsoleSpanExporter())
            _logger.info("OTel: using ConsoleSpanExporter (fallback)")

        try:
            provider.add_span_processor(processor)
        except Exception as exc:
            _logger.warning("OTel: failed to add span processor: %s", exc)
    trace.set_tracer_provider(provider)
    try:
        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
    except Exception:
        pass
    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
    except Exception:
        pass
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        RequestsInstrumentor().instrument()
    except Exception:
        pass
    _initialized = True


def get_tracer(name: str = "shopsquire"):
    return trace.get_tracer(name)
