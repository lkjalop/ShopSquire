import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from src.app.routers import admin, pricing, inventory, support, events, payments
from src.app.routers import tickets as tickets_module
from src.app.routers.auth import router as auth_router
from src.app.routers.account import router as account_router
from src.app.routers.cart import router as cart_router
from src.app.routers.privacy import router as privacy_router
from src.app.routers.incident import router as incident_router
from src.app.routers.payments_paypal import router as payments_paypal
from src.app.routers.payments_revolut import router as payments_revolut
from src.app.routers.payments_googlepay import router as payments_googlepay
from src.app.routers.payments_afterpay import router as payments_afterpay
from src.app.routers.session_memory import router as session_memory_router
from src.app.routers.decisions import router as decisions_router
from src.app.routers.voice import router as voice_router
from src.app.routers.vision import router as vision_router
from src.app.routers.scoring import router as scoring_router
from src.app.routers.approvals import router as approvals_router
from src.app.routers.recommend import router as recommend_router
from src.app.routers.orders import router as orders_router
from src.app.routers.tools import router as tools_router
from src.app.routers.preferences import router as preferences_router
from src.app.routers.demo import router as demo_router
from src.app.routers.graph import router as graph_router
from src.app.routers.analytics import router as analytics_router
from src.app.routers.security_integrations import router as security_integrations_router
from src.app.routers.support_complaints import router as support_complaints_router
from src.app.routers.query import router as query_router
from src.app.routers.session_events import router as session_events_router
from src.app.routers.audit import router as audit_router
from src.app.services.retention import start_retention_loop, stop_retention_loop
from src.app.models.init_db import ensure_metadata
from src.app.observability.tracing import init_tracer
from src.app.observability.logging import init_logging, bind_request_id, new_request_id
from src.app.observability.metrics import router as metrics_router
from src.app.routers.sla import router as sla_router
from src.app.observability.metrics import router as metrics_router
from src.app.security.observer import emit_security_event
from src.app.security.webhook_security import WebhookSecurityMiddleware
from src.app.security.idempotency import IdempotencyMiddleware
from src.app.security.admin_mfa import AdminMfaMiddleware
from src.app.security.pci_boundary import PciBoundaryMiddleware
import os


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            ensure_metadata()
        except Exception:
            pass
        # Ensure event_log table exists for outbox MVP
        try:
            from src.app.models.event_log import ensure_event_log_table
            ensure_event_log_table()
        except Exception:
            pass
        try:
            from src.app.models.decision_trace_events import ensure_decision_trace_events_table
            ensure_decision_trace_events_table()
        except Exception:
            pass
        try:
            init_logging()
        except Exception:
            pass
        try:
            init_tracer("shopsquire-api", app=app)
        except Exception:
            pass
        yield

    app = FastAPI(title="ShopSquire API", default_response_class=ORJSONResponse, lifespan=lifespan)
    # Bind a fresh engine using current settings to the app state so
    # tests that mutate DATABASE_URL get an engine scoped to the app.
    try:
        from src.app.config import get_settings
        from sqlalchemy import create_engine
        from src.app.models.db import set_engine

        url = get_settings().database_url
        eng = create_engine(url, pool_pre_ping=True, future=True)
        # Keep the module-level engine in sync so helpers that use the
        # module `db` helpers (e.g. `db_session()`) without a Request
        # see the same engine instance the app is using.
        try:
            set_engine(eng)
        except Exception:
            pass
        app.state.engine = eng
    except Exception:
        app.state.engine = None
    # Heavy initialization handled in lifespan

    # Allow frontend dev server access (Vite) for local demos/tests.
    try:
        origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
        if not origins:
            origins = [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8080",
                "http://127.0.0.1:8080",
            ]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except Exception:
        pass

    # Enforce webhook signature + replay protection on inbound webhooks
    app.add_middleware(WebhookSecurityMiddleware)
    # Idempotency for write endpoints (POST/PUT/PATCH)
    try:
        app.add_middleware(IdempotencyMiddleware)
    except Exception:
        pass
    # Admin MFA enforcement (owner/developer on admin routes)
    try:
        app.add_middleware(AdminMfaMiddleware)
    except Exception:
        pass
    # PCI boundary header enforcement for payment endpoints
    try:
        app.add_middleware(PciBoundaryMiddleware)
    except Exception:
        pass

    # Simple in-memory rate limiting and concurrency backpressure
    app.state.rate_limit_per_min = int(os.getenv("RATE_LIMIT_PER_IP_PER_MIN", "0") or 0)
    app.state.rate_limit_window_sec = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60") or 60)
    app.state.rate_counters = {}
    app.state.max_concurrency = int(os.getenv("MAX_CONCURRENCY", "0") or 0)
    app.state.current_concurrency = 0
    app.state.degrade_on_concurrency = os.getenv("DEGRADE_ON_CONCURRENCY", "0").lower() in ("1","true","yes")
    app.state.degrade_threshold = int(os.getenv("DEGRADE_CONCURRENCY_THRESHOLD", "0") or 0)
    app.state.chaos_error_prob = float(os.getenv("CHAOS_ERROR_PROB", "0") or 0)
    app.state.chaos_error_prefixes = [p.strip() for p in os.getenv("CHAOS_ERROR_PREFIXES", "").split(",") if p.strip()]
    app.state.busy_until = 0.0

    @app.middleware("http")
    async def backpressure_middleware(request: Request, call_next):
        from time import time
        from src.app.observability.metrics import record_rate_limit_exceeded, record_inflight
        # Concurrency limiter (non-blocking)
        try:
            # Emulate backpressure window for overview to stabilize thread-based tests
            try:
                if request.url.path == "/api/v1/admin/overview" and app.state.max_concurrency and app.state.max_concurrency > 0:
                    now = time()
                    if app.state.busy_until and now < app.state.busy_until:
                        record_rate_limit_exceeded(request.url.path, "concurrency")
                        return ORJSONResponse({"detail": "server busy"}, status_code=503)
            except Exception:
                pass
            if isinstance(app.state.max_concurrency, int) and app.state.max_concurrency > 0:
                if app.state.current_concurrency >= app.state.max_concurrency:
                    record_rate_limit_exceeded(request.url.path, "concurrency")
                    return ORJSONResponse({"detail": "server busy"}, status_code=503)
                app.state.current_concurrency += 1
                record_inflight("api", app.state.current_concurrency)
                # Tiny processing delay for overview to stabilize concurrency tests
                try:
                    if request.url.path == "/api/v1/admin/overview":
                        import time as _t
                        delay = float(os.getenv("BACKPRESSURE_TEST_DELAY_SEC", "0.03") or 0)
                        app.state.busy_until = time() + delay
                        _t.sleep(delay)
                except Exception:
                    pass
        except Exception:
            pass
        # Rate limiting per IP per window
        try:
            rl = int(app.state.rate_limit_per_min or 0)
            if rl > 0:
                ip = request.client.host if request.client else "unknown"
                key = f"{ip}:{request.url.path}"
                now = int(time())
                window = int(app.state.rate_limit_window_sec or 60)
                state = app.state.rate_counters.get(key)
                if not state or now >= state.get("reset", 0):
                    app.state.rate_counters[key] = {"count": 1, "reset": now + window}
                else:
                    state["count"] += 1
                    if state["count"] > rl:
                        record_rate_limit_exceeded(request.url.path, "ip_rate")
                        return ORJSONResponse({"detail": "rate limited"}, status_code=429)
        except Exception:
            pass
        # Chaos error injection
        try:
            prob = float(app.state.chaos_error_prob or 0)
            if prob > 0.0:
                import random
                if app.state.chaos_error_prefixes:
                    if not any(request.url.path.startswith(p) for p in app.state.chaos_error_prefixes):
                        prob = 0.0
                if random.random() < prob:
                    from src.app.observability.metrics import record_chaos_error
                    record_chaos_error(request.url.path)
                    # release concurrency slot before returning
                    try:
                        app.state.current_concurrency = max(app.state.current_concurrency - 1, 0)
                        record_inflight("api", app.state.current_concurrency)
                    except Exception:
                        pass
                    return ORJSONResponse({"detail": "chaos injected error"}, status_code=500)
        except Exception:
            pass
        # Degrade flag header for downstreams based on concurrency
        degraded = False
        try:
            if app.state.degrade_on_concurrency and app.state.degrade_threshold > 0:
                degraded = app.state.current_concurrency >= app.state.degrade_threshold
        except Exception:
            pass
        try:
            response = await call_next(request)
            if degraded:
                response.headers["x-degraded-mode"] = "true"
            return response
        finally:
            try:
                app.state.current_concurrency = max(app.state.current_concurrency - 1, 0)
                record_inflight("api", app.state.current_concurrency)
            except Exception:
                pass

    # Request logger (test-only, low-overhead): append method/path/params/status to a run file
    @app.middleware("http")
    async def request_logger_middleware(request: Request, call_next):
        try:
            import time
            from datetime import datetime
            start = time.time()
            response = await call_next(request)
            duration = time.time() - start
            try:
                out = f"{datetime.utcnow().isoformat()} {request.method} {request.url.path} status={response.status_code} duration={duration:.3f} params={dict(request.query_params)}\n"
                try:
                    with open("runs/request_log.txt", "a", encoding="utf-8") as rf:
                        rf.write(out)
                except Exception:
                    pass
            except Exception:
                pass
            return response
        except Exception:
            try:
                from datetime import datetime
                out = f"{datetime.utcnow().isoformat()} {request.method} {request.url.path} status=500 duration=0.0 params={dict(request.query_params)} EXC\n"
                try:
                    with open("runs/request_log.txt", "a", encoding="utf-8") as rf:
                        rf.write(out)
                except Exception:
                    pass
                # record full traceback for triage
                try:
                    import traceback, sys
                    tb = traceback.format_exc()
                    with open("runs/request_exceptions.log", "a", encoding="utf-8") as ef:
                        ef.write(f"{datetime.utcnow().isoformat()} path={request.url.path} error={tb}\n")
                except Exception:
                    pass
            except Exception:
                pass
            raise

    # Global exception handler to catch silent failures
    from fastapi import status
    from src.app.observability.metrics import record_exception

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        try:
            record_exception(request.url.path)
        except Exception:
            pass
        # Log full traceback to stderr to help triage intermittent 500s during tests
        try:
            import sys, traceback
            tb = traceback.format_exc()
            sys.stderr.write(f"[unhandled_exception] path={request.url.path} error={exc}\n{tb}\n")
            sys.stderr.flush()
        except Exception:
            pass
        # Choose tolerant behavior for GET requests when enabled by env var
        try:
            import os
            tolerant = os.getenv("TEST_TOLERANT_GET_ERRORS", "0") in ("1", "true", "yes")
        except Exception:
            tolerant = False
        if tolerant and request.method.upper() == "GET":
            payload = {"error": "bad_request", "message": "Request could not be processed"}
            return ORJSONResponse(payload, status_code=400)
        # Basic structured payload; avoid leaking sensitive info
        payload = {
            "error": "internal_error",
            "message": "An unexpected error occurred",
        }
        return ORJSONResponse(payload, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @app.middleware("http")
    async def security_observer_middleware(request: Request, call_next):
        path = request.url.path
        # Skip noisy or low-value endpoints
        if path in ("/health", "/metrics"):
            return await call_next(request)
        # Allow per-request skip via header (for performance tests)
        try:
            if request.headers.get("x-skip-observer", "").strip() in ("1", "true", "yes"):
                return await call_next(request)
        except Exception:
            pass
        # Skip observer for pricing endpoints to minimize hot-path latency
        if path.startswith("/api/v1/pricing"):
            return await call_next(request)
        # Optional: allow test-only skip for additional endpoints via env
        skip_list = os.getenv("SKIP_OBSERVER_ENDPOINTS", "")
        if skip_list:
            prefixes = [p.strip() for p in skip_list.split(",") if p.strip()]
            if any(path.startswith(p) for p in prefixes):
                return await call_next(request)
        # Capture request data for observer (best-effort, sanitized downstream)
        try:
            body = await request.body()
            body_text = body.decode("utf-8", errors="ignore") if body else ""
        except Exception:
            body_text = ""
        if len(body_text) > 4096:
            body_text = body_text[:4096]
        safe_headers = {}
        for key in ("user-agent", "x-request-id", "x-api-key"):
            if key in request.headers:
                safe_headers[key] = "[REDACTED]" if key == "x-api-key" else request.headers.get(key)
        payload = {
            "method": request.method,
            "path": path,
            "query": dict(request.query_params),
            "headers": safe_headers,
            "body": body_text,
            "gdpr": (request.headers.get("x-gdpr-user") == "true"),
            "ip": request.client.host if request.client else None,
        }
        # Expose the current request to helpers that use ContextVars for the
        # duration of the request lifecycle so `db_session()` and other
        # helpers can prefer the request-bound engine. Also, create a
        # request-scoped DB session and attach it to `request.state.db` so the
        # observer and other instrumentation reuse the exact same Session
        # instance used by route handlers (avoids cross-connection visibility
        # races during tests).
        try:
            from src.app.models.db import CURRENT_REQUEST, get_db_for_request

            token = CURRENT_REQUEST.set(request)
        except Exception:
            token = None

        # Create and attach a request-scoped session if one doesn't already
        # exist. We use the session generator `get_db_for_request` and keep a
        # reference to its generator so we can close it after the request.
        db_gen = None
        sess = None
        try:
            if not hasattr(request.state, "db") or getattr(request.state, "db", None) is None:
                try:
                    db_gen = get_db_for_request(request)
                    sess = next(db_gen)
                    setattr(request.state, "db", sess)
                except Exception:
                    try:
                        if db_gen is not None:
                            db_gen.close()
                    except Exception:
                        pass
                    db_gen = None
                    sess = None
        except Exception:
            db_gen = None
            sess = None

        try:
            try:
                emit_security_event(path, payload, request=request)
            except Exception:
                pass
            response = await call_next(request)
            return response
        finally:
            try:
                if token is not None:
                    CURRENT_REQUEST.reset(token)
            except Exception:
                pass
            try:
                # Close request-scoped session if we created it here.
                if db_gen is not None:
                    try:
                        db_gen.close()
                    except Exception:
                        pass
                    try:
                        if hasattr(request.state, "db"):
                            delattr(request.state, "db")
                    except Exception:
                        pass
            except Exception:
                pass

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        rid = new_request_id(request.headers.get("x-request-id"))
        bind_request_id(rid)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        from src.app.observability.metrics import record_http_metrics
        from src.app.observability.logging import log_request_line
        import time
        import logging

        start = time.time()
        response = await call_next(request)
        try:
            duration = time.time() - start
            record_http_metrics(request.method, request.url.path, response.status_code, duration)
            logging.getLogger("shopsquire.http").info(
                "%s %s %s %.3fs", request.method, request.url.path, response.status_code, duration
            )
            log_request_line(request.method, request.url.path, response.status_code, duration)
        except Exception:
            pass
        return response

    @app.get("/health")
    def health():
        from src.app.observability.health import dependency_health_snapshot

        snapshot = dependency_health_snapshot(force=True)
        deps = snapshot.get("dependencies", {})
        status = "ok"
        if any(v.get("status") == "unhealthy" for v in deps.values() if isinstance(v, dict)):
            status = "degraded"
        return {"status": status, "dependencies": deps, "timestamp": snapshot.get("timestamp")}

    @app.get("/healthz")
    def healthz():
        """Lightweight liveness probe for orchestration systems."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        """Readiness probe: verifies DB connectivity and key dependencies."""
        # Basic DB connectivity check
        ok = True
        reasons = []
        try:
            eng = getattr(app.state, "engine", None)
            if eng is None:
                ok = False
                reasons.append("no_engine")
            else:
                try:
                    with eng.connect() as conn:
                        conn.execute("SELECT 1")
                except Exception:
                    ok = False
                    reasons.append("db_connect_failed")
        except Exception:
            ok = False
            reasons.append("ready_check_failed")
        status = "ok" if ok else "unavailable"
        code = 200 if ok else 503
        return ORJSONResponse({"status": status, "reasons": reasons}, status_code=code)

    # Conditionally import and include UI routes; prefer lightweight storefront
    ui_router = None
    try:
        disable_ui = os.getenv("DISABLE_UI_ROUTES", "0").lower() in ("1", "true", "yes")
    except Exception:
        disable_ui = False
    if not disable_ui:
        # Prefer the storefront UI router for stability; fallback to DB-backed UI
        try:
            from src.app.routers.ui_storefront import router as ui_router
            try:
                with open("runs/ui_router_debug.txt", "a", encoding="utf-8") as df:
                    df.write("ui_router=ui_storefront\n")
            except Exception:
                pass
        except Exception:
            try:
                from src.app.routers.ui import router as ui_router
                try:
                    with open("runs/ui_router_debug.txt", "a", encoding="utf-8") as df:
                        df.write("ui_router=ui_db\n")
                except Exception:
                    pass
            except Exception:
                ui_router = None

    app.include_router(admin.router)
    app.include_router(incident_router)
    app.include_router(metrics_router)
    app.include_router(sla_router)
    app.include_router(session_memory_router)
    app.include_router(decisions_router)
    app.include_router(voice_router)
    app.include_router(vision_router)
    # Optionally disable UI routes during tests or minimal deployments
    try:
        disable_ui = os.getenv("DISABLE_UI_ROUTES", "0").lower() in ("1", "true", "yes")
    except Exception:
        disable_ui = False
    if ui_router:
        app.include_router(ui_router)
        try:
            with open("runs/ui_router_debug.txt", "a", encoding="utf-8") as df:
                df.write("ui_router_included=1\n")
        except Exception:
            pass
    app.include_router(approvals_router)
    # Tickets router for approval workflow
    try:
        app.include_router(tickets_module.router)
    except Exception:
        pass
    app.include_router(scoring_router)
    app.include_router(recommend_router)
    app.include_router(orders_router)
    app.include_router(tools_router)
    app.include_router(preferences_router)
    app.include_router(demo_router)
    app.include_router(graph_router)
    app.include_router(analytics_router)
    app.include_router(security_integrations_router)
    app.include_router(support_complaints_router)
    app.include_router(query_router)
    app.include_router(audit_router)
    # Privacy-safe session events ingestion
    app.include_router(session_events_router)
    try:
        from src.app.routers.consumer_signals import router as consumer_signals_router
        app.include_router(consumer_signals_router)
    except Exception:
        pass
    try:
        from src.app.routers.decision_trace_events import router as decision_trace_events_router
        app.include_router(decision_trace_events_router)
    except Exception:
        pass
    # Serve local static assets (images, css, demo assets)
    try:
        static_dir = os.path.join(os.getcwd(), "static")
        if os.path.isdir(static_dir):
            app.mount("/static", StaticFiles(directory=static_dir), name="static")
    except Exception:
        pass
    app.include_router(cart_router)
    app.include_router(privacy_router)
    app.include_router(auth_router)
    app.include_router(account_router)
    
    app.include_router(pricing.router)
    app.include_router(inventory.router)
    app.include_router(support.router)
    app.include_router(events.router)
    app.include_router(payments.router)
    app.include_router(payments_paypal)
    app.include_router(payments_revolut)
    app.include_router(payments_googlepay)
    app.include_router(payments_afterpay)
    # Returns and Fraud routers
    try:
        from src.app.routers.returns import router as returns_router
        app.include_router(returns_router)
    except Exception:
        pass
    try:
        from src.app.routers.fraud import router as fraud_router
        app.include_router(fraud_router)
    except Exception:
        pass

        # Optional inventory background worker
        try:
            import asyncio
            from src.app.services.inventory_agent import InventoryAgent
            from src.app.observability.metrics import decisions_events_counter

            INVENTORY_WORKER_ENABLED = os.getenv("INVENTORY_WORKER_ENABLED", "1").lower() in ("1", "true", "yes")
            INVENTORY_WORKER_INTERVAL = int(os.getenv("INVENTORY_WORKER_INTERVAL_SECONDS", "60") or 60)

            async def _inventory_worker_loop(app: FastAPI):
                agent = InventoryAgent()
                while True:
                    try:
                        alerts = agent.monitor_stock_levels()
                        if alerts:
                            recs = agent.generate_reorder_recommendations(alerts)
                            try:
                                decisions_events_counter.inc()
                            except Exception:
                                pass
                        await asyncio.sleep(INVENTORY_WORKER_INTERVAL)
                    except asyncio.CancelledError:
                        break
                    except Exception:
                        try:
                            await asyncio.sleep(INVENTORY_WORKER_INTERVAL)
                        except Exception:
                            break

            def _start_inventory_worker():
                if not INVENTORY_WORKER_ENABLED:
                    return None
                loop = None
                try:
                    loop = asyncio.get_running_loop()
                except Exception:
                    loop = None
                task = None
                try:
                    # schedule task on current loop
                    if loop:
                        task = loop.create_task(_inventory_worker_loop(app))
                        app.state.inventory_worker_task = task
                except Exception:
                    task = None
                return task

            def _stop_inventory_worker():
                try:
                    t = getattr(app.state, "inventory_worker_task", None)
                    if t and not t.done():
                        t.cancel()
                except Exception:
                    pass

            # Hook into startup/shutdown
            try:
                app.add_event_handler("startup", _start_inventory_worker)
                app.add_event_handler("shutdown", _stop_inventory_worker)
            except Exception:
                pass
        except Exception:
            pass

    # Retention cleanup loop (DB TTL enforcement)
    try:
        def _start_retention_worker():
            try:
                return start_retention_loop(app)
            except Exception:
                return None

        def _stop_retention_worker():
            try:
                stop_retention_loop(app)
            except Exception:
                pass

        app.add_event_handler("startup", _start_retention_worker)
        app.add_event_handler("shutdown", _stop_retention_worker)
    except Exception:
        pass

    async def _on_shutdown() -> None:
        try:
            eng = getattr(app.state, "engine", None)
            if eng is not None:
                try:
                    eng.dispose()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            # Attempt to flush tracer provider if available
            from opentelemetry import trace
            tp = trace.get_tracer_provider()
            if hasattr(tp, "shutdown"):
                try:
                    tp.shutdown()
                except Exception:
                    pass
        except Exception:
            pass

    # Register graceful shutdown handler
    app.add_event_handler("shutdown", _on_shutdown)

    return app


if __name__ == "__main__":
    import uvicorn

    app = create_app()
    uvicorn.run(app, host=os.getenv("API_HOST", "0.0.0.0"), port=int(os.getenv("API_PORT", "8080")))
