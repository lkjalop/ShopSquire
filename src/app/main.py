import os
import json
import logging
import re
import shutil
import subprocess
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from fastapi.responses import ORJSONResponse, HTMLResponse, RedirectResponse
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
from src.app.routers.image_sidecar import router as image_sidecar_router
from src.app.routers.cv import router as cv_router
from src.app.routers.recruiting import router as recruiting_router
from src.app.routers.scoring import router as scoring_router
from src.app.routers.approvals import router as approvals_router
from src.app.routers.fulfillment_cases import router as fulfillment_cases_router
from src.app.routers.supply_risk import router as supply_risk_router
from src.app.routers.kyv_admin import router as kyv_admin_router
from src.app.routers.recommend_compat import router as recommend_router
from src.app.routers.recommend_aux import router as recommend_aux_router
from src.app.routers.recommendation_checkout import router as recommendation_checkout_router
from src.app.routers.recommendation_explain import router as recommendation_explain_router
from src.app.routers.recommendation_nqe import router as recommendation_nqe_router
from src.app.routers.recommendation_feedback import router as recommendation_feedback_router
from src.app.routers.products_compare import router as products_router
from src.app.routers.orchestrator_api import router as orchestrator_router
from src.app.routers.orders import router as orders_router
from src.app.routers.tools import router as tools_router
from src.app.routers.preferences import router as preferences_router
from src.app.routers.graph import router as graph_router
from src.app.routers.analytics import router as analytics_router
from src.app.routers.query_clusters import router as clusters_router
from src.app.routers.security_integrations import router as security_integrations_router
from src.app.routers.shipping_security import router as shipping_security_router
from src.app.routers.shipping_webhooks import router as shipping_webhooks_router
from src.app.routers.support_complaints import router as support_complaints_router
from src.app.routers.query import router as query_router
from src.app.routers.session_events import router as session_events_router
from src.app.routers.chat import router as chat_router
from src.app.routers.safe_links import router as safe_links_router
from src.app.routers.billing import router as billing_router
from src.app.routers.admin_webhooks import router as admin_webhooks_router
from src.app.routers.audit import router as audit_router
from src.app.routers.posthoc import router as posthoc_router
from src.app.routers.health import router as health_router
from src.app.routers.trace_debug import router as trace_debug_router
from src.app.routers.admin_chat_tools import router as admin_chat_tools_router
from src.app.routers.escalation_room import router as escalation_room_router
from src.app.routers.escalation_room import public_router as public_incidents_router
from src.app.routers.admin_bi import router as admin_bi_router
from src.app.routers.data_readiness import router as data_readiness_router
from src.app.services.retention import start_retention_loop, stop_retention_loop
from src.app.models.init_db import ensure_metadata
from sqlalchemy import text as sql_text
from src.app.observability.tracing import init_tracer
from src.app.observability.logging import init_logging, bind_request_id, new_request_id
from src.app.observability.metrics import router as metrics_router
from src.app.observability.init import instrument_app
from src.app.routers.sla import router as sla_router
from src.app.security.observer import emit_security_event
from src.app.security.webhook_security import WebhookSecurityMiddleware
from src.app.security.idempotency import IdempotencyMiddleware
from src.app.security.admin_mfa import AdminMfaMiddleware
from src.app.security.pci_boundary import PciBoundaryMiddleware
from src.app.security.compliance import ComplianceMiddleware
from src.app.security.headers import SecurityHeadersMiddleware
from src.app.security.csrf_middleware import CSRFMiddleware
from src.app.security.rate_limit import (
    RateLimitMiddleware,
    consume_fixed_window_limit,
    acquire_concurrency_slot,
    release_concurrency_slot,
)
from src.app.security.internal_mtls import InternalMTLSMiddleware
from src.app.security.tls_fingerprint_middleware import TLSFingerprintMiddleware
from src.app.security.request_shape import GlobalRequestShapeMiddleware


def _is_non_dev_env() -> bool:
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env not in ("local", "dev", "development", "test")


def _cv_ocr_runtime_snapshot(provider: str | None = None) -> dict[str, Any]:
    """Return CV OCR runtime readiness, including OS-level binary checks.

    Probes ONLY the packages the selected provider can use: importing paddleocr
    loads the full Paddle framework (whose model-source check stalls ~10-15s when
    its source is blocked), so the boot-path probe must never pay that cost for a
    provider that doesn't need it (glm-ocr/embedded run via Ollama — no local OCR).
    An unprobed package is ABSENT from deps ("not probed"), never reported False
    ("probed and missing"). The exhaustive all-dependency introspection lives in
    the role-gated cv_readiness diagnostic, not on the boot path."""
    selected = (provider or os.getenv("CV_OCR_PROVIDER", "auto") or "auto").strip().lower()
    no_local_ocr = selected in ("disabled", "none", "off", "embedded", "glm-ocr", "glm_ocr", "ollama-ocr")

    def _probe(*pkgs: str) -> None:
        for pkg in pkgs:
            try:
                __import__(pkg)
                deps[pkg] = True
            except Exception:
                deps[pkg] = False

    deps: dict[str, bool] = {}
    _probe("pyzbar")  # QR-decode runtime is provider-independent and cheap
    if selected == "tesseract":
        _probe("pytesseract")
    elif selected == "paddle":
        _probe("paddleocr", "cv2")
    elif not no_local_ocr:  # auto: probe the cheap leg now; paddle only if it's needed (below)
        _probe("pytesseract")

    runtime: dict[str, Any] = {}
    reasons: list[str] = []

    # pytesseract requires a runtime binary; import success alone is insufficient.
    tess_path = shutil.which("tesseract")
    runtime["tesseract_path"] = tess_path
    runtime["tesseract_bin"] = bool(tess_path)
    if deps.get("pytesseract") and tess_path:
        try:
            proc = subprocess.run([tess_path, "--version"], capture_output=True, text=True, timeout=2)
            runtime["tesseract_version_ok"] = proc.returncode == 0
            if proc.returncode != 0:
                reasons.append("tesseract_version_probe_failed")
        except Exception:
            runtime["tesseract_version_ok"] = False
            reasons.append("tesseract_version_probe_failed")
    elif deps.get("pytesseract") and not tess_path:
        reasons.append("tesseract_binary_missing")

    # pyzbar requires libzbar runtime.
    if deps.get("pyzbar"):
        try:
            from pyzbar.pyzbar import decode as _decode  # type: ignore

            runtime["pyzbar_runtime"] = bool(_decode)
        except Exception:
            runtime["pyzbar_runtime"] = False
            reasons.append("pyzbar_runtime_missing")
    else:
        runtime["pyzbar_runtime"] = False

    if no_local_ocr:
        ready = True  # glm-ocr uses Ollama — no local binary required
    elif selected == "tesseract":
        ready = bool(deps.get("pytesseract") and runtime.get("tesseract_bin"))
        if not ready:
            reasons.append("tesseract_provider_not_ready")
    elif selected == "paddle":
        ready = bool(deps.get("paddleocr") and deps.get("cv2"))
        if not ready:
            reasons.append("paddle_provider_not_ready")
    else:
        # auto: the cheap tesseract leg was probed above; pay the paddle import
        # only when that leg cannot serve.
        ready = bool(deps.get("pytesseract") and runtime.get("tesseract_bin"))
        if not ready:
            _probe("paddleocr", "cv2")
            ready = bool(deps.get("paddleocr") and deps.get("cv2"))
        if not ready:
            reasons.append("no_available_ocr_provider")

    return {
        "provider": selected,
        "ready": bool(ready),
        "deps": deps,
        "runtime": runtime,
        "reasons": list(dict.fromkeys([str(r) for r in reasons if str(r)])),
    }


def _prewarm_router_models(app: FastAPI) -> dict[str, Any]:
    """Load the bounded router and taxonomy models and publish truthful readiness."""
    result: dict[str, Any] = {"ready": False, "status": "warming"}
    app.state.router_prewarm = result
    try:
        import httpx

        from src.app.services.recommendation_core.turn_router import _router_model
        from src.app.services.taxonomy_embedding_index import EMBED_MODEL

        url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        model = _router_model()
        # Warm the optional taxonomy embedder first and the latency-critical router last. When
        # Ollama is configured for one resident model, the inverse order evicts the router just
        # before the first buyer turn and turns readiness into a misleading cold-start claim.
        embed = httpx.post(
            f"{url}/api/embed",
            json={
                "model": EMBED_MODEL,
                "input": ["product taxonomy warmup"],
                "keep_alive": os.getenv("OLLAMA_EMBED_KEEP_ALIVE", "60m"),
            },
            timeout=120.0,
        )
        embed.raise_for_status()
        generate = httpx.post(
            f"{url}/api/generate",
            json={
                "model": model,
                "prompt": "ok",
                "stream": False,
                "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                "options": {"num_predict": 1, "temperature": 0},
            },
            timeout=120.0,
        )
        generate.raise_for_status()
        result = {
            "ready": True,
            "status": "ready",
            "router_model": model,
            "embedding_model": EMBED_MODEL,
        }
    except Exception as exc:
        result = {"ready": False, "status": "failed", "error": str(exc)[:300]}
    app.state.router_prewarm = result
    return result


def _vlm_warmup_enabled() -> bool:
    """Resolve startup VLM warming without evicting the demo text router."""
    raw = os.getenv("VLM_WARMUP_ON_START")
    if raw is not None:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    profile = str(os.getenv("SHOPSQUIRE_RUNTIME_PROFILE", "") or "").strip().lower()
    return profile != "demo_v2"


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Ensure migrations are applied for non-SQLite DBs.
        try:
            from src.app.models.migration_guard import ensure_migrations

            ensure_migrations()
        except Exception:
            raise
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
            from src.app.security.security_event_ingest import ensure_security_event_ingest_table
            ensure_security_event_ingest_table()
        except Exception:
            pass
        try:
            from src.app.services.playbook_engine import ensure_playbook_run_tables
            ensure_playbook_run_tables()
        except Exception:
            pass
        try:
            from src.app.services.audit_chain import ensure_audit_chain_table
            ensure_audit_chain_table()
        except Exception:
            pass
        # Eagerly validate AUDIT_CHAIN_SECRET at startup so a misconfigured production
        # deployment fails immediately rather than silently forging audit records.
        try:
            from src.app.security.audit_chain import _get_chain_secret
            _get_chain_secret()
        except RuntimeError as _audit_err:
            import logging as _al
            _al.getLogger("shopsquire.startup").critical(
                "STARTUP BLOCKED: %s — set AUDIT_CHAIN_SECRET before starting in production.", _audit_err
            )
            raise  # Abort startup — do not run with a broken audit chain in prod
        except Exception:
            pass
        try:
            from src.app.services.intake_gate import ensure_qr_allowlist_table
            ensure_qr_allowlist_table()
        except Exception:
            pass
        try:
            from src.app.services.supplier_domain_guard import ensure_trusted_supplier_domains_table
            ensure_trusted_supplier_domains_table()
        except Exception:
            pass
        try:
            from src.app.routers.admin_email_security import ensure_investigation_actions_table
            ensure_investigation_actions_table()
        except Exception:
            pass
        try:
            init_logging()
        except Exception:
            pass
        # LOUD memory-store guard (must run AFTER init_logging or the OK line is dropped by the
        # last-resort handler): a dead Redis does not stop the app — it silently degrades into
        # per-call connection timeouts and LITERAL context loss (session memory gone). That failure
        # mode cost days of confused latency numbers and would cost a live demo its memory. Scream
        # at startup; the /health checker screams ONCE on every up/down transition at runtime.
        try:
            import logging as _rl
            _redis_log = _rl.getLogger("shopsquire.startup")
            try:
                from src.app.deps import get_redis as _gr
                _rc = _gr()
                if type(_rc).__name__ == "DummyRedis":  # the dev fallback answers in-process — a lie
                    raise ConnectionError("DummyRedis fallback active (Redis was down at first use)")
                if hasattr(_rc, "ping"):
                    _rc.ping()
                _redis_log.info("memory store (Redis) reachable — session memory ACTIVE")
            except Exception as _rerr:
                _redis_log.critical(
                    "\n" + "!" * 78 +
                    "\n!! MEMORY STORE (Redis) UNREACHABLE: %s"
                    "\n!! The app will RUN but with NO session memory (context loss every turn) and"
                    "\n!! multi-second connection timeouts inflating EVERY request's latency."
                    "\n!! Fix: start Docker Desktop, then `docker compose up -d redis`."
                    "\n" + "!" * 78, str(_rerr)[:120],
                )
        except Exception:
            pass
        try:
            init_tracer("shopsquire-api", app=app)
        except Exception:
            pass
        # Pre-warm the decision-log/audit path OFF-THREAD: the first request otherwise pays a
        # ~2.7s cold spike in decision_log_and_annotation (metadata create + column introspection
        # + trace-table init + first hash-chain write, in aggregate). One synthetic-but-honest
        # 'service_started' decision row absorbs all of it before any buyer arrives.
        try:
            import threading as _th

            def _prewarm_decision_log() -> None:
                try:
                    from src.app.models.decision_trace_events import ensure_decision_trace_events_table
                    from src.app.models.init_db import ensure_metadata
                    from src.app.services.decision_log import log_decision
                    ensure_metadata()
                    ensure_decision_trace_events_table()
                    log_decision(
                        agent_name="system_startup",
                        input_data={"event": "service_started"},
                        retrieved_context={},
                        proposed_action={"action": "prewarm_decision_log"},
                        agent_reasoning="startup pre-warm: absorb first-write init cost before user traffic",
                        policy_version="v1",
                        approval_required=False,
                        execution_status="executed",
                    )
                    import logging as _pl
                    _pl.getLogger("shopsquire.startup").info("decision-log pre-warm complete")
                except Exception as _pw_exc:
                    import logging as _pl
                    _pl.getLogger("shopsquire.startup").warning("decision-log pre-warm failed: %s", _pw_exc)

            _app_env_for_audit = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
            _audit_prewarm_on = str(os.getenv(
                "DECISION_LOG_PREWARM_ON_START",
                "0" if _app_env_for_audit in ("test", "testing") else "1",
            )).strip().lower() in ("1", "true", "yes", "on")
            if _audit_prewarm_on:
                _th.Thread(
                    target=_prewarm_decision_log,
                    name="decision-log-prewarm",
                    daemon=True,
                ).start()
        except Exception:
            pass
        # Router-model preload OFF-THREAD: absorb the cold-load spike AND keep the router model
        # resident so a concurrent vision request (glm-ocr) can't evict it mid-session. Measured:
        # warm+pinned the router routes in ~5-6s (PASS the 8s gate); cold-or-evicted it spikes to
        # 11-13s — the "latency blocker" was VRAM eviction, not model speed. Pair with
        # OLLAMA_MAX_LOADED_MODELS>=2 so the router and the VLM coexist instead of thrashing.
        # Off by default under test envs (no Ollama on CI); best-effort everywhere.
        try:
            _app_env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
            _prewarm_on = str(
                os.getenv("ROUTER_PREWARM_ON_START", "0" if _app_env in ("test", "testing") else "1")
            ).strip().lower() in ("1", "true", "yes", "on")
            if _prewarm_on:
                import threading as _th2

                def _prewarm_router_model() -> None:
                    result = _prewarm_router_models(app)
                    import logging as _rl2
                    if result.get("ready"):
                        _rl2.getLogger("shopsquire.startup").info(
                            "router/taxonomy-model pre-warm complete: %s + %s",
                            result.get("router_model"), result.get("embedding_model"),
                        )
                    else:
                        _rl2.getLogger("shopsquire.startup").warning(
                            "router-model pre-warm failed: %s", result.get("error"),
                        )

                _blocking = str(os.getenv("ROUTER_PREWARM_BLOCKING", "0")).strip().lower() in (
                    "1", "true", "yes", "on",
                )
                if _blocking:
                    _prewarm_router_model()
                else:
                    _th2.Thread(
                        target=_prewarm_router_model, name="router-model-prewarm", daemon=True,
                    ).start()
        except Exception:
            pass
        try:
            from sqlalchemy import text as _sql_text
            from scripts.seed_demo_data import seed_products
            from src.app.models.db import db_session

            if str(os.getenv("AUTO_SEED_CATALOG_ON_START", "1")).lower() in ("1", "true", "yes"):
                with db_session() as db:
                    active_products = db.execute(
                        _sql_text("SELECT COUNT(*) FROM products WHERE active IS TRUE")
                    ).scalar() or 0
                    if int(active_products) <= 0:
                        # Cold/empty catalog bootstrap.
                        seed_products(db)
                    try:
                        from src.app.platform.store_profile import active_profile_id
                        profile_id = str(active_profile_id() or "").strip().lower()
                        raw_gaming_seed = os.getenv("AUTO_SEED_GAMING_CATALOG_ON_START")
                        app_env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
                        local_default = app_env in ("local", "dev", "development", "test", "testing")
                        gaming_seed_enabled = (
                            str(raw_gaming_seed).strip().lower() in ("1", "true", "yes", "on")
                            if raw_gaming_seed is not None else local_default
                        )
                        if profile_id == "electronics" and gaming_seed_enabled:
                            # Idempotent and self-healing: adds missing GAM-* rows and aligned inventory
                            # for stale local demo DBs without putting vertical logic in core scoring.
                            from scripts.seed_gaming_laptops import ensure_gaming_catalog
                            ensure_gaming_catalog(db)
                        elif profile_id and profile_id != "electronics" and local_default:
                            # Non-electronics vertical (fashion/pharmacy/…): seed its OWN profile catalog
                            # into products+inventory so the switched store runs real DB retrieval, not
                            # just the zero-result fallback. Agnostic: the seeder reads the profile slot.
                            from scripts.seed_profile_catalog import seed_profile_catalog
                            seed_profile_catalog(db, profile_id)
                        # Supplier coverage tracks the catalog (profile-agnostic) so a recommended SKU
                        # resolves an approved supplier instead of dead-ending at NO_APPROVED_SUPPLIER.
                        raw_suppliers_seed = os.getenv("AUTO_SEED_SUPPLIERS_ON_START")
                        suppliers_seed_enabled = (
                            str(raw_suppliers_seed).strip().lower() in ("1", "true", "yes", "on")
                            if raw_suppliers_seed is not None else local_default
                        )
                        if suppliers_seed_enabled:
                            from src.app.services.supplier_catalog import (
                                ensure_supplier_coverage,
                                seed_demo_supplier_history,
                                seed_demo_vendor_contacts,
                            )
                            ensure_supplier_coverage(db, commit=False)
                            # The vendor and history seeders own independent sessions.
                            # Publish this transaction first so a second SQLite writer
                            # cannot wait behind startup's still-open catalog write.
                            db.commit()
                            seed_demo_vendor_contacts()  # kyv_vendors manage their own session
                            seed_demo_supplier_history()  # supplier_baseline_events — prior-dealings context
                    except Exception:
                        pass
                    db.commit()
        except Exception:
            pass
        # Load plugin registry
        try:
            from src.app.services.registry import load_from_config
            load_from_config(os.getenv("PLUGINS_CONFIG_PATH", "config/plugins.yml"))
        except Exception:
            pass
        try:
            if str(os.getenv("CV_WARMUP_ON_START", "")).lower() in ("1", "true", "yes"):
                from src.app.workers.task_runner import submit_task, register_handler

                def _cv_warmup_handler(payload):
                    from src.app.services.cv_warmup import warmup_cv_models
                    warmup_cv_models()

                register_handler("cv_warmup", _cv_warmup_handler)
                submit_task("cv_warmup", {})
        except Exception:
            pass
        try:
            import logging

            app.state.cv_ocr_smoke = _cv_ocr_runtime_snapshot()
            if not bool((app.state.cv_ocr_smoke or {}).get("ready")):
                logging.getLogger("shopsquire.startup").warning(
                    "cv_ocr_runtime_not_ready: %s", app.state.cv_ocr_smoke
                )
        except Exception:
            app.state.cv_ocr_smoke = {"ready": False, "error": "cv_ocr_smoke_check_failed"}
        try:
            from src.app.services.trace_broker import start_stream_consumer
            await start_stream_consumer()
        except Exception:
            pass
        # Optional CLIP pre-warm. Keep this off by default for the shopping fast
        # path because compromised-image recommendations use safe catalog hints
        # and should not compete with model loading during startup.
        try:
            if str(os.getenv("VISUAL_SEARCH_PREWARM_ON_START", "0")).lower() in ("1", "true", "yes"):
                import asyncio as _asyncio_startup
                from src.app.services.visual_search import _load_clip as _vs_load_clip
                _asyncio_startup.get_event_loop().run_in_executor(None, _vs_load_clip)
        except Exception:
            pass
        # Build visual search index in background on startup
        try:
            if str(os.getenv("VISUAL_SEARCH_INDEX_ON_START", "0")).lower() in ("1", "true", "yes"):
                from src.app.workers.task_runner import submit_task, register_handler

                def _vs_index_handler(payload):
                    import logging
                    from src.app.services.visual_search import build_index, is_available, status, try_load_persisted_index
                    if not is_available():
                        return
                    from src.app.models.db import db_session
                    from sqlalchemy import text as sql_text
                    import json as _json

                    try:
                        if try_load_persisted_index():
                            st = status()
                            fresh = not bool(((st.get("freshness") or {}).get("stale")))
                            if fresh and int(st.get("index_size") or 0) > 0:
                                logging.getLogger("shopsquire.startup").info(
                                    "Visual search index loaded from disk (size=%s, age_s=%s)",
                                    st.get("index_size"),
                                    (st.get("freshness") or {}).get("age_seconds"),
                                )
                                return
                    except Exception:
                        pass

                    products = []
                    max_updated_at = None
                    with db_session() as session:
                        try:
                            rows = session.execute(sql_text(
                                "SELECT sku, name, brand, price_cents, specs, COALESCE(updated_at, created_at) AS ts FROM products LIMIT 50000"
                            )).fetchall()
                        except Exception:
                            rows = session.execute(sql_text(
                                "SELECT sku, name, brand, price_cents, specs FROM products LIMIT 50000"
                            )).fetchall()
                        for r in rows:
                            specs = {}
                            if r[4]:
                                try:
                                    specs = _json.loads(r[4]) if isinstance(r[4], str) else r[4]
                                except Exception:
                                    pass
                            if len(r) > 5 and r[5] is not None:
                                ts = str(r[5])
                                if not max_updated_at or ts > max_updated_at:
                                    max_updated_at = ts
                            products.append({"sku": r[0], "name": r[1], "brand": r[2], "price_cents": r[3], "specs": specs})
                    if products:
                        n = build_index(
                            products,
                            persist=True,
                            source="startup_refresh",
                            catalog_max_updated_at=max_updated_at,
                        )
                        logging.getLogger("shopsquire.startup").info("Visual search index built: %d products", n)

                register_handler("vs_index_build", _vs_index_handler)
                submit_task("vs_index_build", {})
        except Exception:
            pass
        # Auto-index FAQ into faq_embeddings table if empty on startup
        try:
            if str(os.getenv("FAQ_VECTOR_INDEX_ON_START", "0")).lower() in ("1", "true", "yes"):
                from src.app.workers.task_runner import submit_task as _submit, register_handler as _reg

                def _faq_index_handler(payload):
                    import logging
                    _flog = logging.getLogger("shopsquire.startup")
                    try:
                        from src.app.services.vector_store import ensure_vector_table
                        from src.app.models.db import db_session
                        from sqlalchemy import text as _sql
                        ensure_vector_table("faq_embeddings")
                        with db_session() as _db:
                            try:
                                count = _db.execute(_sql("SELECT COUNT(*) FROM faq_embeddings")).scalar() or 0
                            except Exception:
                                count = 0
                        if count > 0:
                            _flog.info("FAQ embeddings already indexed (%d rows), skipping startup index.", count)
                            return
                    except Exception:
                        pass
                    try:
                        from scripts.index_catalog import run_index
                        result = run_index(index_catalog=False, index_faq=True, batch_size=200)
                        import logging as _l2
                        _l2.getLogger("shopsquire.startup").info(
                            "FAQ embedding index built on startup: %s", result
                        )
                    except Exception as _exc:
                        import logging as _l3
                        _l3.getLogger("shopsquire.startup").warning(
                            "FAQ vector index startup failed (non-fatal): %s", _exc
                        )

                _reg("faq_index_build", _faq_index_handler)
                _submit("faq_index_build", {})
        except Exception:
            pass
        # Start task runner consumer (Redis Streams)
        try:
            from src.app.workers.task_runner import start_consumer
            start_consumer()
        except Exception:
            pass
        # VLM cold-start warming: fire a tiny generate request so the first real user request
        # doesn't pay the full model-load latency (typically 4-8 s for qwen3-vl:8b on RTX 5070 Ti).
        try:
            if _vlm_warmup_enabled():
                import asyncio as _asyncio
                import logging as _wlog

                async def _warm_vlm():
                    import httpx
                    _log = _wlog.getLogger("shopsquire.startup")
                    base = (os.getenv("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
                    model = (
                        os.getenv("CV_VISION_MODEL")
                        or os.getenv("OLLAMA_VISION_MODEL")
                        or "qwen3-vl:8b"
                    ).strip()
                    try:
                        async with httpx.AsyncClient(timeout=30.0) as _client:
                            await _client.post(
                                f"{base}/api/generate",
                                json={"model": model, "prompt": "hi", "stream": False, "options": {"num_predict": 1}},
                            )
                        _log.info("VLM warm-up complete: model=%s url=%s", model, base)
                    except Exception as _exc:
                        _log.info("VLM warm-up skipped (Ollama not ready yet): %s", _exc)

                _asyncio.ensure_future(_warm_vlm())
        except Exception:
            pass
        yield
        # Stop task runner consumer
        try:
            from src.app.workers.task_runner import stop_consumer, shutdown_fallback_pool
            stop_consumer()
            shutdown_fallback_pool()
        except Exception:
            pass
        try:
            from src.app.services.trace_broker import stop_stream_consumer
            await stop_stream_consumer()
        except Exception:
            pass
        try:
            from src.app.services.dependency_resilience import (
                shutdown_resilience_executor,
            )
            shutdown_resilience_executor(wait=False)
        except Exception:
            pass
        try:
            from src.app.services.recommend_narration_jobs import (
                shutdown_narration_resources,
            )
            shutdown_narration_resources(wait=False)
        except Exception:
            pass
    app = FastAPI(title="ShopSquire API", default_response_class=ORJSONResponse, lifespan=lifespan)
    # Bind a fresh engine using current settings to the app state so
    # tests that mutate DATABASE_URL get an engine scoped to the app.
    try:
        from src.app.config import get_settings
        from src.app.models import db as dbmod

        # Prefer live env var to avoid cached settings bleeding across tests.
        url = os.getenv("DATABASE_URL") or get_settings().database_url
        # If tests have already set a module-level engine (common test pattern),
        # prefer that engine instance so inserted rows visible to request handlers.
        try:
            existing = getattr(dbmod, "engine", None)
        except Exception:
            existing = None
        prefer_existing = False
        # If a test or external code pre-populated the module-level engine,
        # prefer that instance unconditionally. Tests commonly set `dbmod.engine`
        # to a test-scoped SQLite engine before calling `create_app()`.
        if existing is not None:
            # If tests injected a StaticPool engine (common for SQLite fixtures),
            # always respect it to keep module-level DB fixtures consistent.
            try:
                if existing is not None and existing.pool.__class__.__name__ == "StaticPool":
                    prefer_existing = True
            except Exception:
                prefer_existing = False
            try:
                existing_url = str(getattr(existing, "url", ""))
            except Exception:
                existing_url = ""
            managed = bool(getattr(existing, "_shopsquire_managed", False))
            existing_is_sqlite = "sqlite" in existing_url
            target_is_sqlite = bool(url and "sqlite" in url)

            # If we detected an explicit test engine, keep it.
            if prefer_existing:
                eng = existing
                try:
                    dbmod.set_engine(eng)
                except Exception:
                    pass
            # If the env requests SQLite but the current engine is non-SQLite,
            # honor the env override (common in tests).
            else:
                if target_is_sqlite and not existing_is_sqlite:
                    eng = dbmod.create_runtime_engine(url)
                    try:
                        setattr(eng, "_shopsquire_managed", True)
                    except Exception:
                        pass
                    try:
                        dbmod.set_engine(eng)
                    except Exception:
                        pass
                elif target_is_sqlite and existing_is_sqlite and url and existing_url and existing_url != url:
                    # If tests request a sqlite DB different from the existing engine's URL,
                    # always create a new engine for that URL (including the default
                    # test.sqlite). This preserves per-URL DB isolation so tests that
                    # monkeypatch DATABASE_URL don't share the session engine and
                    # contaminate unrelated test data.
                    eng = dbmod.create_runtime_engine(url)
                    try:
                        setattr(eng, "_shopsquire_managed", True)
                    except Exception:
                        pass
                    try:
                        dbmod.set_engine(eng)
                    except Exception:
                        pass
                elif managed and url and existing_url and existing_url != url:
                    eng = dbmod.create_runtime_engine(url)
                    try:
                        setattr(eng, "_shopsquire_managed", True)
                    except Exception:
                        pass
                    try:
                        dbmod.set_engine(eng)
                    except Exception:
                        pass
                else:
                    eng = existing
                    try:
                        # Ensure sqlite helpers + SessionLocal are registered for test engines
                        dbmod.set_engine(eng)
                    except Exception:
                        pass
        else:
            eng = dbmod.create_runtime_engine(url)
            try:
                setattr(eng, "_shopsquire_managed", True)
            except Exception:
                pass
            try:
                dbmod.set_engine(eng)
            except Exception:
                pass
        app.state.engine = eng
    except Exception:
        app.state.engine = None
    # Heavy initialization handled in lifespan

    # Instrument app with tracing + Prometheus metrics (best-effort)
    try:
        instrument_app(app)
    except Exception:
        pass

    # Allow frontend dev server access (Vite) for local demos/tests.
    # In production, CORS_ORIGINS must be explicitly set — localhost origins are
    # only included when APP_ENV is local/dev or CORS_ORIGINS explicitly lists them.
    try:
        origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
        origin_regex = None
        if not origins:
            _app_env = os.getenv("APP_ENV", "local").strip().lower()
            if _app_env in ("local", "dev", "development", "test", "testing"):
                # DEV: allow ANY localhost/127.0.0.1 port so a demo on an alternate frontend port (5178, …)
                # or backend port just works — no per-port CORS edit. allow_origin_regex echoes the specific
                # origin, so it's compatible with allow_credentials (a wildcard '*' would not be). PROD still
                # requires explicit CORS_ORIGINS below.
                origin_regex = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"
                origins = []
            else:
                # Production: no wildcard fallback — require explicit CORS_ORIGINS
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "CORS_ORIGINS not set in APP_ENV=%s — CORS will be restrictive (no allowed origins). "
                    "Set CORS_ORIGINS env var to your frontend domain(s).",
                    _app_env,
                )
                origins = []
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_origin_regex=origin_regex,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    except Exception:
        pass

    # Security response headers (CSP, HSTS, X-Frame-Options, etc.)
    try:
        app.add_middleware(SecurityHeadersMiddleware)
    except Exception:
        pass
    # CRIT-08: CSRF double-submit protection on all state-changing API routes
    try:
        app.add_middleware(CSRFMiddleware)
    except Exception:
        pass
    # API version deprecation headers (RFC-8594 Deprecation / Sunset)
    try:
        from src.app.versioning import VersionDeprecationMiddleware
        app.add_middleware(VersionDeprecationMiddleware)
    except Exception:
        pass
    # Enforce webhook signature + replay protection on inbound webhooks
    app.add_middleware(WebhookSecurityMiddleware)
    # M06: Patch httpx globally to enforce egress domain allowlist (dead-drop prevention)
    try:
        from src.app.security.egress_allowlist import patch_outbound_egress_guard
        patch_outbound_egress_guard()
    except Exception:
        pass
    # Enforce proxy-validated mTLS headers for internal service routes when enabled.
    try:
        app.add_middleware(InternalMTLSMiddleware)
    except Exception:
        pass
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
        # Skip PCI boundary middleware in test/dev when explicitly disabled
        if os.getenv("DISABLE_SECURITY_MIDDLEWARE", "0").lower() not in ("1", "true", "yes"):
            app.add_middleware(PciBoundaryMiddleware)
    except Exception:
        pass
    # Compliance middleware (PCI detection + per-request compliance flags)
    try:
        app.add_middleware(ComplianceMiddleware)
    except Exception:
        pass
    # Global request body and JSON shape caps (fail-safe in non-dev).
    # Added after other middlewares so it executes first in request flow.
    try:
        app.add_middleware(GlobalRequestShapeMiddleware)
    except Exception:
        pass

    # Simple in-memory rate limiting and concurrency backpressure
    # Token-bucket rate limiting
    # In non-dev environments, default to a non-zero IP limit unless explicitly overridden.
    default_ip_rate = "60" if _is_non_dev_env() else "0"
    app.state.rate_limit_per_min = int(os.getenv("RATE_LIMIT_PER_IP_PER_MIN", default_ip_rate) or default_ip_rate)
    app.state.rate_limit_window_sec = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60") or 60)
    app.state.rate_buckets = {}  # key -> {tokens, last_refill}
    app.state.scoped_rate_buckets = {}  # key -> {start, count}
    app.state.scoped_tenant_rate_buckets = {}  # key -> {start, count}
    app.state.write_schema_guard_enabled = str(os.getenv("WRITE_SCHEMA_GUARD_ENABLED", "1")).lower() in ("1", "true", "yes")
    app.state.max_write_json_bytes = int(os.getenv("MAX_WRITE_JSON_BYTES", "262144") or 262144)
    app.state.max_concurrency = int(os.getenv("MAX_CONCURRENCY", "0") or 0)
    app.state.current_concurrency = 0
    app.state.degrade_on_concurrency = os.getenv("DEGRADE_ON_CONCURRENCY", "0").lower() in ("1","true","yes")
    app.state.degrade_threshold = int(os.getenv("DEGRADE_CONCURRENCY_THRESHOLD", "0") or 0)
    app.state.chaos_error_prob = float(os.getenv("CHAOS_ERROR_PROB", "0") or 0)
    app.state.chaos_error_prefixes = [p.strip() for p in os.getenv("CHAOS_ERROR_PREFIXES", "").split(",") if p.strip()]
    app.state.busy_until = 0.0

    # Install lightweight rate-limit middleware (per-key + per-IP)
    try:
        default_per_key = "120" if _is_non_dev_env() else "0"
        default_per_ip = "60" if _is_non_dev_env() else "0"
        per_key = int(os.getenv("RATE_LIMIT_PER_MINUTE_KEY", default_per_key) or default_per_key)
        per_ip = int(os.getenv("RATE_LIMIT_PER_MINUTE_IP", default_per_ip) or default_per_ip)
        app.add_middleware(RateLimitMiddleware, per_min_key=per_key, per_min_ip=per_ip)
    except Exception:
        pass
    # Capture JA3/JA4 headers from trusted ingress proxies for fraud scoring.
    # Added last so it runs first — fingerprint data is available to all downstream middleware and handlers.
    try:
        app.add_middleware(TLSFingerprintMiddleware)
    except Exception:
        pass

    # Scope the active StoreProfile (vertical) per request: X-Store-Profile header → STORE_PROFILE_ID
    # env → electronics. Pure-ASGI so the ContextVar reaches the (threadpool-run) sync routes — turns
    # the agnostic core from env-level into per-tenant runtime selection.
    try:
        from src.app.platform.store_profile_middleware import StoreProfileMiddleware
        app.add_middleware(StoreProfileMiddleware)
    except Exception:
        pass

    # Batch the recommend route's durable trace writes into one bulk insert (latency): begins a
    # trace batch on entry, flushes after the response. Pure-ASGI so the batch ContextVar reaches
    # the threadpool-run sync route. Scoped to /api/v1/recommend.
    try:
        from src.app.platform.trace_batch_middleware import TraceBatchMiddleware
        app.add_middleware(TraceBatchMiddleware)
    except Exception:
        pass

    @app.middleware("http")
    async def backpressure_middleware(request: Request, call_next):
        from time import time
        from src.app.observability.metrics import record_rate_limit_exceeded, record_inflight
        method = (request.method or "").upper()
        path = request.url.path

        def _scope_for_path(p: str) -> str | None:
            if p.startswith("/api/v1/recommend"):
                return "recommend"
            if p.startswith("/api/v1/cart"):
                return "cart"
            if p.startswith("/api/v1/orders") or p.startswith("/api/v1/payments"):
                return "checkout"
            if p.startswith("/api/v1/admin"):
                return "admin"
            return None

        def _scoped_limit(scope: str, kind: str) -> int:
            defaults = {
                ("recommend", "ip"): 180,
                ("recommend", "tenant"): 240,
                ("cart", "ip"): 180,
                ("cart", "tenant"): 240,
                ("checkout", "ip"): 90,
                ("checkout", "tenant"): 140,
                ("admin", "ip"): 120,
                ("admin", "tenant"): 180,
            }
            env_key = f"RATE_LIMIT_{scope.upper()}_{kind.upper()}_PER_MIN"
            return int(os.getenv(env_key, str(defaults.get((scope, kind), 0))) or 0)

        def _consume_fixed_window(bucket_store: dict, key: str, limit: int, win_sec: int, now_ts: float) -> bool:
            return consume_fixed_window_limit(
                key=key,
                limit=limit,
                window_sec=win_sec,
                fallback_store=bucket_store,
                now_ts=now_ts,
            )

        def _write_allowlist_for(p: str, m: str) -> dict[str, Any] | None:
            if m not in {"POST", "PUT", "PATCH", "DELETE"}:
                return None
            if p == "/api/v1/recommend/interaction":
                return {"keys": {"uid", "sku", "action", "surface", "trace_id", "context"}}
            if p == "/api/v1/recommend/nqe_feedback":
                # Backward-compatible allowlist across old and new NQE payloads.
                return {"keys": {"uid", "trace_id", "question_id", "answer", "accepted", "meta", "tenant_id", "variant", "converted", "latency_ms"}}
            if p == "/api/v1/cart/items":
                if m == "POST":
                    return {"keys": {"uid", "sku", "quantity"}}
                if m == "PUT":
                    return {"keys": {"uid", "items"}, "nested": {"items": {"sku", "quantity"}}}
            if p == "/api/v1/orders/create":
                return {"keys": {"uid", "items", "customer_id", "guest_email", "trace_id"}, "nested": {"items": {"sku", "quantity"}}}
            if p == "/api/v1/orders/guest/lookup":
                return {"keys": {"order_id", "email"}}
            if p.startswith("/api/v1/admin/") and m in {"POST", "PUT", "PATCH", "DELETE"}:
                # Admin endpoints are varied; block obvious prompt injection keys while allowing route-owned schema.
                return {"deny_keys_regex": r"(?i)(system_prompt|developer_override|raw_sql|drop_table|exec_shell)"}
            return None

        async def _validate_write_payload() -> ORJSONResponse | None:
            if not bool(app.state.write_schema_guard_enabled):
                return None
            if method not in {"POST", "PUT", "PATCH", "DELETE"}:
                return None
            if not path.startswith("/api/v1/"):
                return None
            cfg = _write_allowlist_for(path, method)
            if not cfg:
                return None
            ct = (request.headers.get("content-type") or "").lower()
            if "multipart/form-data" in ct:
                return None
            try:
                body = await request.body()
            except Exception:
                body = b""
            if not body:
                return None
            if len(body) > int(app.state.max_write_json_bytes or 262144):
                return ORJSONResponse({"detail": "payload too large"}, status_code=413)
            if ct and ("application/json" not in ct):
                return ORJSONResponse({"detail": "content-type must be application/json"}, status_code=415)
            try:
                obj = json.loads(body.decode("utf-8"))
            except Exception:
                return ORJSONResponse({"detail": "invalid json body"}, status_code=400)
            if isinstance(obj, dict):
                deny_pat = cfg.get("deny_keys_regex")
                if deny_pat:
                    bad = [k for k in obj.keys() if re.search(str(deny_pat), str(k))]
                    if bad:
                        return ORJSONResponse({"detail": "unsafe keys rejected", "keys": bad[:6]}, status_code=422)
                allow = cfg.get("keys")
                if isinstance(allow, set):
                    unknown = [k for k in obj.keys() if k not in allow]
                    if unknown:
                        return ORJSONResponse({"detail": "unknown fields", "keys": sorted(unknown)[:8]}, status_code=422)
                nested = cfg.get("nested") or {}
                for nkey, nallow in nested.items():
                    val = obj.get(nkey)
                    if isinstance(val, list):
                        for idx, item in enumerate(val[:100]):
                            if isinstance(item, dict):
                                un = [k for k in item.keys() if k not in nallow]
                                if un:
                                    return ORJSONResponse(
                                        {"detail": f"unknown fields in {nkey}[{idx}]", "keys": sorted(un)[:8]},
                                        status_code=422,
                                    )
            return None

        write_guard_resp = await _validate_write_payload()
        if write_guard_resp is not None:
            return write_guard_resp
        # Concurrency limiter (non-blocking)
        try:
            # Emulate backpressure for overview to stabilize thread-based tests
            try:
                if request.url.path == "/api/v1/admin/overview" and app.state.max_concurrency and app.state.max_concurrency > 0:
                    now = time()
                    # If a previous request declared a short busy window, enforce it.
                    if float(getattr(app.state, "busy_until", 0.0) or 0.0) > now:
                        record_rate_limit_exceeded(request.url.path, "concurrency")
                        return ORJSONResponse({"detail": "server busy"}, status_code=503)
                    # If we already have a slot taken beyond threshold, return busy
                    if app.state.current_concurrency >= app.state.max_concurrency:
                        record_rate_limit_exceeded(request.url.path, "concurrency")
                        return ORJSONResponse({"detail": "server busy"}, status_code=503)
                    # Mark a short busy window to increase determinism for concurrent requests
                    try:
                        delay = float(os.getenv("BACKPRESSURE_TEST_DELAY_SEC", "0.03") or 0)
                        app.state.busy_until = now + delay
                    except Exception:
                        pass
            except Exception:
                pass
            if isinstance(app.state.max_concurrency, int) and app.state.max_concurrency > 0:
                if app.state.current_concurrency >= app.state.max_concurrency:
                    record_rate_limit_exceeded(request.url.path, "concurrency")
                    return ORJSONResponse({"detail": "server busy"}, status_code=503)
                app.state.current_concurrency += 1
                record_inflight("api", app.state.current_concurrency)
                # Tiny async delay for overview to stabilize concurrency tests without blocking the event loop.
                try:
                    if request.url.path == "/api/v1/admin/overview":
                        delay = float(os.getenv("BACKPRESSURE_TEST_DELAY_SEC", "0.03") or 0)
                        if delay > 0:
                            import asyncio as _asyncio_bp
                            await _asyncio_bp.sleep(delay)
                except Exception:
                    pass
        except Exception:
            pass
        # Chaos error injection (run before rate limiting so chaos tests are deterministic)
        try:
            prob = float(app.state.chaos_error_prob or 0)
            if prob > 0.0:
                import random
                # Skip chaos injection for explicit test skips or when observer skip list includes the path
                try:
                    if str(request.headers.get("x-skip-observer", "0")) in ("1", "true", "yes"):
                        prob = 0.0
                except Exception:
                    pass
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
        # Rate limiting per IP using fixed window counters
        try:
            rl = int(app.state.rate_limit_per_min or 0)
            try:
                if str(request.headers.get("x-skip-observer", "0")) in ("1", "true", "yes"):
                    rl = 0
            except Exception:
                pass
            if rl > 0:
                ip = request.client.host if request.client else "unknown"
                key = f"ip:{ip}:path:{request.url.path}"
                now = time()
                win = int(app.state.rate_limit_window_sec or 60)
                if not consume_fixed_window_limit(
                    key=key,
                    limit=rl,
                    window_sec=win,
                    fallback_store=app.state.rate_buckets,
                    now_ts=now,
                ):
                    record_rate_limit_exceeded(request.url.path, "ip_rate")
                    return ORJSONResponse({"detail": "rate limited"}, status_code=429)
        except Exception:
            pass
        # Scoped P0 limits (per-IP + per-tenant) for recommend/cart/checkout/admin paths.
        try:
            scope = _scope_for_path(path)
            if scope:
                now = time()
                win = int(app.state.rate_limit_window_sec or 60)
                ip = request.client.host if request.client else "unknown"
                tenant = request.headers.get("x-tenant-id") or request.query_params.get("tenant_id") or "default"
                ip_lim = _scoped_limit(scope, "ip")
                tenant_lim = _scoped_limit(scope, "tenant")
                ip_key = f"{scope}:ip:{ip}"
                tenant_key = f"{scope}:tenant:{tenant}"
                if not _consume_fixed_window(app.state.scoped_rate_buckets, ip_key, ip_lim, win, now):
                    record_rate_limit_exceeded(path, f"{scope}_ip_rate")
                    return ORJSONResponse({"detail": "rate limited", "scope": scope, "dimension": "ip"}, status_code=429)
                if not _consume_fixed_window(app.state.scoped_tenant_rate_buckets, tenant_key, tenant_lim, win, now):
                    record_rate_limit_exceeded(path, f"{scope}_tenant_rate")
                    return ORJSONResponse({"detail": "rate limited", "scope": scope, "dimension": "tenant"}, status_code=429)
        except Exception:
            pass
        # Per-tenant concurrency limits
        try:
            tenant = request.headers.get("x-tenant-id") or request.query_params.get("tenant_id") or "default"
            if not hasattr(app.state, "tenant_concurrency"):
                app.state.tenant_concurrency = {}
            lim = int(os.getenv("TENANT_MAX_CONCURRENCY", "0") or 0)
            if lim > 0:
                ttl = int(os.getenv("TENANT_CONCURRENCY_TTL_SEC", "75") or 75)
                tenant_slot_key = f"tenant:{tenant}"
                acquired = acquire_concurrency_slot(
                    key=tenant_slot_key,
                    limit=lim,
                    ttl_sec=ttl,
                    fallback_store=app.state.tenant_concurrency,
                )
                if not acquired:
                    record_rate_limit_exceeded(request.url.path, "tenant_concurrency")
                    return ORJSONResponse({"detail": "tenant busy"}, status_code=503)
                request.state._tenant_concurrency_slot = tenant_slot_key
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
            # Release tenant slot
            try:
                slot_key = getattr(request.state, "_tenant_concurrency_slot", None)
                if slot_key:
                    release_concurrency_slot(
                        key=str(slot_key),
                        fallback_store=(app.state.tenant_concurrency if hasattr(app.state, "tenant_concurrency") else None),
                    )
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
                    import traceback
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

    @app.exception_handler(RequestValidationError)
    async def _request_validation_exception_handler(request: Request, exc: RequestValidationError):
        # FastAPI's default encoder can crash when validation error payload includes raw bytes
        # (e.g., multipart binary uploads sent to JSON endpoints). Return a safe 422 payload.
        def _safe(v):
            if isinstance(v, bytes):
                return f"<binary:{len(v)} bytes>"
            if isinstance(v, dict):
                return {k: _safe(val) for k, val in v.items()}
            if isinstance(v, list):
                return [_safe(x) for x in v]
            return v

        try:
            detail = _safe(exc.errors())
        except Exception:
            detail = [{"type": "validation_error", "msg": "Request validation failed"}]
        return ORJSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        # ── Handle structured ShopSquireError subclasses ──
        try:
            from src.app.exceptions import ShopSquireError
            if isinstance(exc, ShopSquireError):
                try:
                    record_exception(request.url.path)
                except Exception:
                    pass
                return ORJSONResponse(exc.to_dict(), status_code=exc.status_code)
        except ImportError:
            pass

        try:
            record_exception(request.url.path)
        except Exception:
            pass
        # Log full traceback to stderr to help triage intermittent 500s
        try:
            import sys
            import traceback
            tb = traceback.format_exc()
            sys.stderr.write(f"[unhandled_exception] path={request.url.path} error={exc}\n{tb}\n")
            sys.stderr.flush()
        except Exception:
            pass
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
        if request.method == "OPTIONS" or path in ("/health", "/healthz", "/metrics"):
            return await call_next(request)
        if path.startswith("/api/v1/vision/triage"):
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
            ct = (request.headers.get("content-type") or "").lower()
            if "multipart/form-data" in ct:
                body_text = "[multipart omitted]"
            else:
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
            # NEW-3: bound the observer so a cold-start blocking detector / GeoIP / DB call can't hang
            # the request hot path. The bounded path runs emit + anomaly in a worker thread under a hard
            # timeout. CONCURRENCY-GATED DEFAULT-OFF (OBSERVER_THREADED): the threaded path uses a
            # SEPARATE db_session, which is correct on Postgres (per-thread connections) but unsafe on a
            # shared single-connection pool (SQLite/tests → "cannot start a transaction within a
            # transaction", and on timeout the un-cancellable thread keeps writing on that connection).
            # With the flag off (default) the observer runs INLINE on the request-scoped session — the
            # proven, race-free path. Enable OBSERVER_THREADED in prod (Postgres) for the hard time-bound.
            import asyncio as _aio
            import logging as _logging

            def _run_observer_sync(_obs_request):
                try:
                    emit_security_event(path, payload, request=_obs_request)
                except Exception:
                    pass
                # Anomaly detection hook (model-poison / DDOS signals).
                try:
                    from src.app.security.anomaly_detector import detect_anomaly
                    from src.app.observability.metrics import record_security_event
                    an = detect_anomaly(payload)
                    if isinstance(an, dict) and an.get("anomaly"):
                        try:
                            if an.get("severity") in ("high", "critical"):
                                from src.app.services.ticketing import TicketingAgent
                                t = TicketingAgent()
                                title = f"Anomaly detected: {an.get('reason')}"
                                desc = str({"path": path, "reason": an.get("reason"), "payload_summary": payload.get("body") if isinstance(payload, dict) else None})
                                t.create_ticket(title=title, description=desc, severity=(an.get("severity") or "high"))
                        except Exception:
                            pass
                        try:
                            record_security_event("anomaly_detected", an.get("severity") or "medium", an.get("reason") or "anomaly")
                        except Exception:
                            pass
                except Exception:
                    pass

            _obs_threaded = str(os.getenv("OBSERVER_THREADED", "0")).strip().lower() in ("1", "true", "yes", "on")
            if _obs_threaded:
                # Bounded best-effort: own db_session (thread-safe on Postgres), hard timeout.
                _obs_budget = float(os.getenv("OBSERVER_TIMEOUT_SEC", "2.0") or 2.0)
                try:
                    await _aio.wait_for(_aio.to_thread(lambda: _run_observer_sync(None)), timeout=_obs_budget)
                except _aio.TimeoutError:
                    _logging.getLogger("shopsquire.observer").warning(
                        "security observer timed out (%.1fs) on %s — skipped; request continues", _obs_budget, path
                    )
                except Exception:
                    pass
            else:
                # Default: inline on the request-scoped session — no cross-connection race.
                _run_observer_sync(request)
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
        from src.app.services.runtime_modes import runtime_mode_snapshot

        runtime_modes = runtime_mode_snapshot()
        if str(os.getenv("TEST_FAST_HEALTH", "0")).strip().lower() in ("1", "true", "yes", "on"):
            return {
                "status": "ok",
                "mode": "fast_test_health",
                "runtime_modes": runtime_modes,
                "dependencies": {
                    "backend": {"status": "healthy", "mode": "fast_test_health"},
                },
                "timestamp": None,
            }
        from src.app.observability.health import dependency_health_snapshot

        snapshot = dependency_health_snapshot(force=True)
        deps = snapshot.get("dependencies", {})
        status = "ok"
        if any(v.get("status") == "unhealthy" for v in deps.values() if isinstance(v, dict)):
            status = "degraded"
        return {
            "status": status,
            "runtime_modes": runtime_modes,
            "dependencies": deps,
            "timestamp": snapshot.get("timestamp"),
        }

    @app.get("/healthz")
    def healthz():
        """Lightweight liveness probe for orchestration systems."""
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz(deep: bool = False, force: bool = False):
        """Readiness probe.

        Default mode is intentionally fast and local for UI/test polling. Use
        ``?deep=true`` or ``/diagnostics/dependencies`` for external probes.
        """
        ok = True
        reasons: list[str] = []
        config_report = {"ok": True, "missing": [], "warnings": [], "contract": {}}
        components: dict[str, dict[str, Any]] = {
            "backend": {"status": "ready", "details": {"liveness": "ok"}},
            "runtime_profile": {"status": "unknown", "details": {}},
            "frontend": {"status": "skipped", "details": {"mode": "deep_only"}},
            "ollama": {"status": "skipped", "details": {"mode": "deep_only"}},
            "cv_ocr": {"status": "skipped", "details": {"mode": "deep_only"}},
            "redis": {"status": "skipped", "details": {"mode": "deep_only"}},
            "db": {"status": "unknown", "details": {}},
            "router_model": {"status": "unknown", "details": {}},
        }

        def _set_component(name: str, ready: bool, details: dict[str, Any] | None = None) -> None:
            if name not in components:
                return
            components[name] = {"status": "ready" if ready else "not_ready", "details": details or {}}

        try:
            from src.app.config import validate_runtime_contract

            config_report = validate_runtime_contract()
            if not bool(config_report.get("ok")):
                ok = False
                reasons.append("config_contract_invalid")
        except Exception:
            ok = False
            reasons.append("config_contract_check_failed")

        try:
            from src.app.services.runtime_modes import runtime_mode_snapshot

            runtime_modes = runtime_mode_snapshot()
            _set_component("runtime_profile", bool(runtime_modes["ready"]), runtime_modes)
            if not bool(runtime_modes["ready"]):
                ok = False
                reasons.append("runtime_profile_mismatch")
        except Exception:
            ok = False
            reasons.append("runtime_profile_check_failed")
            _set_component("runtime_profile", False, {"error": "runtime_profile_check_failed"})

        try:
            eng = getattr(app.state, "engine", None)
            if eng is None:
                ok = False
                reasons.append("no_engine")
                _set_component("db", False, {"error": "no_engine"})
            else:
                try:
                    with eng.connect() as conn:
                        conn.execute(sql_text("SELECT 1"))
                    _set_component("db", True)
                except Exception:
                    ok = False
                    reasons.append("db_connect_failed")
                    _set_component("db", False, {"error": "db_connect_failed"})
        except Exception:
            ok = False
            reasons.append("ready_check_failed")
            _set_component("db", False, {"error": "ready_check_failed"})

        router_prewarm = getattr(app.state, "router_prewarm", None)
        if isinstance(router_prewarm, dict):
            router_ready = bool(router_prewarm.get("ready"))
            _set_component("router_model", router_ready, router_prewarm)
            if not router_ready and str(os.getenv("ROUTER_PREWARM_REQUIRED", "0")).strip().lower() in (
                "1", "true", "yes", "on",
            ):
                ok = False
                reasons.append("router_model_not_ready")
        else:
            _set_component("router_model", False, {"status": "not_started"})

        if deep:
            try:
                from src.app.observability.health import dependency_health_snapshot

                snap = dependency_health_snapshot(force=force)
                deps = (snap or {}).get("dependencies") or {}
                for dep_name in ("redis", "ollama"):
                    dep = deps.get(dep_name) if isinstance(deps, dict) else None
                    if isinstance(dep, dict):
                        dep_ok = str(dep.get("status") or "").lower() == "healthy"
                        _set_component(dep_name, dep_ok, dep)
                        if dep_name == "redis" and not dep_ok:
                            ok = False
                            reasons.append("redis_unhealthy")
            except Exception:
                _set_component("redis", False, {"error": "health_snapshot_failed"})
                ok = False
                reasons.append("redis_check_failed")

            try:
                import urllib.request as _urlreq

                frontend_url = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173")
                req = _urlreq.Request(frontend_url, method="GET")
                with _urlreq.urlopen(req, timeout=1.5) as resp:
                    status_code = int(getattr(resp, "status", 0) or 0)
                    _set_component("frontend", status_code < 500, {"url": frontend_url, "status_code": status_code})
            except Exception as exc:
                _set_component("frontend", False, {"url": os.getenv("FRONTEND_URL", "http://127.0.0.1:5173"), "error": str(exc)})

            try:
                cv_smoke = _cv_ocr_runtime_snapshot()
                _set_component("cv_ocr", bool(cv_smoke.get("ready")), cv_smoke)
            except Exception as exc:
                _set_component(
                    "cv_ocr",
                    False,
                    {"provider": os.getenv("CV_OCR_PROVIDER", "auto"), "error": str(exc)},
                )

        status = "ok" if ok else "unavailable"
        code = 200 if ok else 503
        return ORJSONResponse(
            {
                "status": status,
                "mode": "deep" if deep else "fast",
                "reasons": reasons,
                "config": config_report,
                "components": components,
            },
            status_code=code,
        )

    @app.get("/diagnostics/dependencies")
    def diagnostics_dependencies(force: bool = False):
        """Deep dependency snapshot for diagnostics pages and manual checks."""
        from src.app.observability.health import dependency_health_snapshot

        return dependency_health_snapshot(force=force)

    def _status_summary_payload() -> dict[str, Any]:
        warn_count = 0
        err_count = 0
        outbound_count = 0
        try:
            eng = getattr(app.state, "engine", None)
            if eng is not None:
                with eng.connect() as conn:
                    try:
                        warn_count = int(
                            conn.execute(sql_text("SELECT COUNT(1) FROM email_security_incidents WHERE severity = 'warning'"))
                            .scalar()
                            or 0
                        )
                    except Exception:
                        warn_count = 0
                    try:
                        err_count = int(
                            conn.execute(sql_text("SELECT COUNT(1) FROM email_security_incidents WHERE severity = 'error'"))
                            .scalar()
                            or 0
                        )
                    except Exception:
                        err_count = 0
                    try:
                        outbound_count = int(
                            conn.execute(sql_text("SELECT COUNT(1) FROM outbound_email_anomalies"))
                            .scalar()
                            or 0
                        )
                    except Exception:
                        outbound_count = 0
        except Exception:
            pass

        return {
            "status": "ok",
            "email_xdr": {"warnings": warn_count, "errors": err_count},
            "outbound_anomalies": outbound_count,
        }

    @app.get("/status/summary")
    def status_summary():
        """Public demo-friendly summary of key Email XDR counts."""
        return ORJSONResponse(_status_summary_payload())

    @app.get("/api/v1/status/summary")
    def status_summary_v1():
        """Compatibility alias for frontend clients expecting /api/v1 prefix."""
        return ORJSONResponse(_status_summary_payload())

    if str(os.getenv("ENABLE_DEMO_ROUTES", "0")).strip().lower() in ("1", "true", "yes", "on"):
        @app.get("/demo", response_class=HTMLResponse)
        @app.get("/demo/links", response_class=HTMLResponse)
        def demo_links():
            """Dev-only demo landing page."""
            warn_count = 0
            err_count = 0
            outbound_count = 0
            try:
                eng = getattr(app.state, "engine", None)
                if eng is not None:
                    with eng.connect() as conn:
                        try:
                            warn_count = int(
                                conn.execute(sql_text("SELECT COUNT(1) FROM email_security_incidents WHERE severity = 'warning'"))
                                .scalar()
                                or 0
                            )
                        except Exception:
                            warn_count = 0
                        try:
                            err_count = int(
                                conn.execute(sql_text("SELECT COUNT(1) FROM email_security_incidents WHERE severity = 'error'"))
                                .scalar()
                                or 0
                            )
                        except Exception:
                            err_count = 0
                        try:
                            outbound_count = int(
                                conn.execute(sql_text("SELECT COUNT(1) FROM outbound_email_anomalies"))
                                .scalar()
                                or 0
                            )
                        except Exception:
                            outbound_count = 0
            except Exception:
                pass

            html = f"""
        <!doctype html>
        <html>
            <head>
                <meta charset='utf-8' />
                <title>ShopSquire Demo Links</title>
                <style>
                    body {{ font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; color: #222; }}
                    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }}
                    .card {{ border: 1px solid #eee; border-radius: 12px; padding: 14px; box-shadow: 0 1px 2px rgba(0,0,0,0.06); }}
                    .title {{ font-size: 18px; margin: 0 0 8px; }}
                    .sub {{ color: #666; font-size: 12px; margin-top: 6px; }}
                    .badge {{ display: inline-block; background: #f5f5f5; border: 1px solid #ddd; border-radius: 999px; padding: 2px 8px; font-size: 12px; margin-left: 8px; }}
                    a.btn {{ display: inline-block; padding: 6px 10px; border-radius: 8px; background: #0b61d6; color: white; text-decoration: none; margin-top: 8px; }}
                    a.btn.secondary {{ background: #555; }}
                </style>
            </head>
            <body>
                <h1>ShopSquire Demo Links</h1>
                <div class='grid'>
                    <div class='card'>
                        <div class='title'>Buyer Site <span class='badge'>vite dev</span></div>
                        <div class='sub'>Storefront UX for checkout + recommendations</div>
                        <a class='btn' href='http://127.0.0.1:5173/' target='_blank' rel='noreferrer'>Open</a>
                    </div>
                    <div class='card'>
                        <div class='title'>Backend Health</div>
                        <div class='sub'>System dependencies snapshot (+ readyz/liveness)</div>
                        <a class='btn' href='http://127.0.0.1:8080/health' target='_blank' rel='noreferrer'>/health</a>
                        <a class='btn secondary' href='/readyz' target='_blank' rel='noreferrer'>/readyz</a>
                        <a class='btn secondary' href='/healthz' target='_blank' rel='noreferrer'>/healthz</a>
                    </div>
                    <div class='card'>
                        <div class='title'>Merchant Dashboard</div>
                        <div class='sub'>Owner-facing, no API key required (dev only)</div>
                        <a class='btn' href='http://127.0.0.1:8080/merchant/dashboard' target='_blank' rel='noreferrer'>Open</a>
                    </div>
                    <div class='card'>
                        <div class='title'>Admin React</div>
                        <div class='sub'>Custom BI + Email XDR + Escalations</div>
                        <a class='btn' href='http://127.0.0.1:3001/' target='_blank' rel='noreferrer'>Open</a>
                    </div>
                    <div class='card'>
                        <div class='title'>Email XDR</div>
                        <div class='sub'>Incidents (warning/error); Outbound anomalies <span class='badge'>admin API key</span></div>
                        <div>
                            <span class='badge'>warnings: {warn_count}</span>
                            <span class='badge'>errors: {err_count}</span>
                            <span class='badge'>outbound anomalies: {outbound_count}</span>
                        </div>
                        <a class='btn secondary' href='/api/v1/admin/email_security/incidents?severity=warning&limit=50' target='_blank' rel='noreferrer'>Incidents (warn)</a>
                        <a class='btn secondary' href='/api/v1/admin/email_security/incidents?severity=error&limit=50' target='_blank' rel='noreferrer'>Incidents (error)</a>
                        <a class='btn secondary' href='/api/v1/admin/email_security/outbound/anomalies' target='_blank' rel='noreferrer'>Outbound anomalies</a>
                    </div>
                    <div class='card'>
                        <div class='title'>API Docs</div>
                        <div class='sub'>OpenAPI schema for REST endpoints</div>
                        <a class='btn secondary' href='/openapi.json' target='_blank' rel='noreferrer'>openapi.json</a>
                    </div>
                </div>
            </body>
        </html>
            """
            return HTMLResponse(content=html)

    @app.get("/", response_class=RedirectResponse)
    def root_redirect():
        """Production-safe root redirect."""
        if str(os.getenv("ENABLE_DEMO_ROUTES", "0")).strip().lower() in ("1", "true", "yes", "on"):
            return RedirectResponse(url="/demo/links")
        return RedirectResponse(url="/health")

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
    try:
        from src.app.routers.admin_mfa_routes import router as admin_mfa_router
        app.include_router(admin_mfa_router)
    except Exception:
        pass
    try:
        from src.app.routers.admin_api_keys import router as admin_api_keys_router
        app.include_router(admin_api_keys_router)
    except Exception:
        pass
    try:
        from src.app.routers.connectors_auth import router as connectors_auth_router
        app.include_router(connectors_auth_router)
    except Exception:
        pass
    # Connectors admin (JWKS management)
    try:
        from src.app.routers.connectors_admin import router as connectors_admin_router
        app.include_router(connectors_admin_router)
    except Exception:
        pass
    # P2: two fully-built admin routers were never included → their endpoints 404'd. Register them
    # (case cockpit: /api/v1/admin/cases/{id}/cockpit+/tags; decision time-travel: /admin/decisions/asof).
    try:
        from src.app.routers.case_cockpit import router as case_cockpit_router
        app.include_router(case_cockpit_router)
    except Exception as e:
        logging.getLogger("shopsquire.startup").exception("failed to include case_cockpit router: %s", e)
    try:
        from src.app.routers.decision_time_travel import router as decision_time_travel_router
        app.include_router(decision_time_travel_router)
    except Exception as e:
        logging.getLogger("shopsquire.startup").exception("failed to include decision_time_travel router: %s", e)
    app.include_router(incident_router)
    app.include_router(metrics_router)
    app.include_router(sla_router)
    app.include_router(session_memory_router)
    app.include_router(decisions_router)
    try:
        from src.app.routers.authz_audit import router as authz_audit_router
        app.include_router(authz_audit_router)
    except Exception as e:
        logging.getLogger("shopsquire.startup").exception("failed to include authz_audit router: %s", e)
    app.include_router(voice_router)
    app.include_router(vision_router)
    app.include_router(image_sidecar_router)
    # CV analysis endpoint (complaints triage)
    try:
        app.include_router(cv_router)
    except Exception:
        pass
    # Visual similarity search (CLIP + FAISS)
    try:
        from src.app.routers.visual_search import router as visual_search_router
        app.include_router(visual_search_router)
    except Exception:
        pass
    try:
        app.include_router(recruiting_router)
    except Exception:
        pass
    # CV readiness/admin endpoints
    try:
        from src.app.routers.cv_readiness import router as cv_readiness_router
        app.include_router(cv_readiness_router)
    except Exception:
        pass
    # OOB verification endpoints (bank-change out-of-band confirmation)
    try:
        from src.app.routers.oob_verification import router as oob_router
        app.include_router(oob_router)
    except Exception:
        pass
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
    app.include_router(fulfillment_cases_router)
    app.include_router(supply_risk_router)
    app.include_router(kyv_admin_router)  # KYV vendor onboarding/lifecycle (autonomous-send trust source)
    # Tickets router for approval workflow
    try:
        app.include_router(tickets_module.router)
    except Exception:
        pass
    app.include_router(scoring_router)
    # Orchestrator public endpoint
    try:
        app.include_router(orchestrator_router)
    except Exception:
        pass
    app.include_router(recommend_router)
    app.include_router(recommend_aux_router)
    app.include_router(recommendation_checkout_router)
    app.include_router(recommendation_explain_router)
    app.include_router(recommendation_nqe_router)
    app.include_router(recommendation_feedback_router)
    # Product catalog and detail endpoints
    try:
        app.include_router(products_router)
    except Exception:
        pass
    # Ensure the static /list route is matched before the dynamic /{sku} route.
    try:
        list_idx = next(
            i for i, r in enumerate(app.routes)
            if getattr(r, "path", None) == "/api/v1/products/list" and "GET" in getattr(r, "methods", set())
        )
        sku_idx = next(
            i for i, r in enumerate(app.routes)
            if getattr(r, "path", None) == "/api/v1/products/{sku}" and "GET" in getattr(r, "methods", set())
        )
        if list_idx > sku_idx:
            route = app.routes.pop(list_idx)
            app.routes.insert(sku_idx, route)
    except Exception:
        pass
    app.include_router(orders_router)
    app.include_router(tools_router)
    app.include_router(preferences_router)
    if str(os.getenv("ENABLE_DEMO_ROUTES", "0")).strip().lower() in ("1", "true", "yes", "on"):
        from src.app.routers.demo import router as demo_router

        app.include_router(demo_router)
    app.include_router(graph_router)
    # Storage presign endpoint
    try:
        from src.app.routers.storage import router as storage_router
        app.include_router(storage_router)
    except Exception:
        pass
    app.include_router(analytics_router)
    # Intent classifier API
    try:
        from src.app.routers.intent import router as intent_router
        app.include_router(intent_router)
    except Exception:
        pass
    app.include_router(clusters_router)
    # Drift daily metrics (admin)
    try:
        from src.app.routers.admin_drift import router as admin_drift_router
        app.include_router(admin_drift_router)
    except Exception:
        pass
    # Admin and merchant UI pages
    try:
        from src.app.routers.admin_analytics import router as admin_analytics_router
        app.include_router(admin_analytics_router)
    except Exception:
        pass
    # Admin supply chain anomaly monitor
    try:
        from src.app.routers.admin_supply_chain import router as admin_supply_chain_router
        app.include_router(admin_supply_chain_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_supply_chain router: %s", e)
    # Supply-chain attack simulation API (safe demo + swarm)
    try:
        from src.app.routers.admin_supply_chain_sim import router as admin_supply_chain_sim_router
        app.include_router(admin_supply_chain_sim_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_supply_chain_sim router: %s", e)
    # Admin fairness audit endpoint (demographic parity)
    try:
        from src.app.routers.admin_fairness import router as admin_fairness_router
        app.include_router(admin_fairness_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_fairness router: %s", e)
    # Email security admin endpoint
    try:
        from src.app.routers.email_security_admin import router as email_security_admin_router
        app.include_router(email_security_admin_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include email_security_admin router: %s", e)
    # Email security evaluation endpoint (owner/developer)
    try:
        from src.app.routers.email_security import router as email_security_router
        app.include_router(email_security_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include email_security router: %s", e)
    # Email connector webhooks (Gmail/M365) - shared-secret auth
    try:
        from src.app.routers.ingest_gmail import router as gmail_ingest_router
        app.include_router(gmail_ingest_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include gmail_ingest router: %s", e)
    try:
        from src.app.routers.ingest_m365 import router as m365_ingest_router
        app.include_router(m365_ingest_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include m365_ingest router: %s", e)
    # Admin drilldown for email incidents
    try:
        from src.app.routers.admin_email_security import router as admin_email_security_router
        app.include_router(admin_email_security_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_email_security router: %s", e)
    # Playbook editor/admin APIs (validate/publish/rollback/dry-run/diff)
    try:
        from src.app.routers.admin_playbooks import router as admin_playbooks_router
        app.include_router(admin_playbooks_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_playbooks router: %s", e)
    # Admin storage health
    try:
        from src.app.routers.admin_storage import router as admin_storage_router
        app.include_router(admin_storage_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_storage router: %s", e)
    # Grafana proxy for embedding dashboards without exposing API key
    try:
        from src.app.routers.admin_grafana_proxy import router as admin_grafana_proxy_router
        app.include_router(admin_grafana_proxy_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_grafana_proxy router: %s", e)
    # Admin email test endpoint
    try:
        from src.app.routers.admin_email import router as admin_email_router
        app.include_router(admin_email_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_email router: %s", e)
    # Outbound-DLP quarantine (owner human-release queue)
    try:
        from src.app.routers.outbound_email_quarantine import router as outbound_quarantine_router
        app.include_router(outbound_quarantine_router)
    except Exception as e:
        import logging
        logging.getLogger("shopsquire.startup").exception("failed to include outbound_email_quarantine router: %s", e)
    # Inventory sync/admin endpoints (Phase 5 MVP)
    try:
        from src.app.routers.admin_inventory import router as admin_inventory_router
        app.include_router(admin_inventory_router)
    except Exception as e:
        try:
            import logging

            logging.getLogger("shopsquire.startup").exception("failed_to_include_admin_inventory_router: %s", e)
        except Exception:
            pass

    try:
        from src.app.routers.allocation import buyer_router as buyer_allocation_router
        from src.app.routers.allocation import router as allocation_router
        app.include_router(allocation_router)
        app.include_router(buyer_allocation_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed_to_include_allocation_router: %s", e)
    try:
        from src.app.routers.case_escalations import router as case_escalations_router

        app.include_router(case_escalations_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception(
            "failed_to_include_case_escalations_router: %s", e
        )
    try:
        from src.app.routers.merchant_dashboard import router as merchant_dashboard_router
        app.include_router(merchant_dashboard_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include merchant_dashboard router: %s", e)
    try:
        from src.app.routers.merchant_intelligence import router as merchant_intelligence_router
        app.include_router(merchant_intelligence_router)
    except Exception as e:
        import logging
        logging.getLogger("shopsquire.startup").exception("failed to include merchant_intelligence router: %s", e)
    app.include_router(security_integrations_router)
    app.include_router(shipping_security_router)
    app.include_router(shipping_webhooks_router)
    # Vulnerability scanning (Trivy / Nuclei / Semgrep / CISA KEV)
    try:
        from src.app.routers.vuln_scan import router as vuln_scan_router
        app.include_router(vuln_scan_router)
    except Exception as e:
        import logging
        logging.getLogger("shopsquire.startup").exception("failed to include vuln_scan router: %s", e)
    app.include_router(support_complaints_router)
    app.include_router(chat_router)
    # Chat streaming SSE endpoint
    try:
        from src.app.routers.chat_stream import router as chat_stream_router
        app.include_router(chat_stream_router)
    except Exception:
        pass
    app.include_router(safe_links_router)
    app.include_router(billing_router)
    app.include_router(admin_webhooks_router)
    try:
        from src.app.routers.shopify_webhooks import router as shopify_webhooks_router

        app.include_router(shopify_webhooks_router)
    except Exception as e:
        logging.getLogger("shopsquire.startup").exception("failed to include shopify_webhooks router: %s", e)
    app.include_router(query_router)
    app.include_router(audit_router)
    app.include_router(posthoc_router)
    app.include_router(health_router)
    # API version metadata endpoint
    try:
        from src.app.versioning import get_api_version_info
        from fastapi import APIRouter as _APIRouter
        _ver_router = _APIRouter(tags=["meta"])

        @_ver_router.get("/api/version", include_in_schema=True)
        def api_version_info():
            return get_api_version_info()

        app.include_router(_ver_router)
    except Exception:
        pass
    # Admin/executive status summary
    try:
        from src.app.routers.status_summary import router as status_summary_router
        app.include_router(status_summary_router)
    except Exception:
        pass
    app.include_router(data_readiness_router)
    app.include_router(trace_debug_router)
    # DMARC ingestion + summary endpoints
    try:
        from src.app.routers.dmarc import router as dmarc_router
        app.include_router(dmarc_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include dmarc router: %s", e)
    # Admin DMARC dashboard + Splunk alerts
    try:
        from src.app.routers.admin_dmarc import router as admin_dmarc_router
        app.include_router(admin_dmarc_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_dmarc router: %s", e)
    try:
        from src.app.routers.admin_compliance_reports import router as admin_compliance_reports_router
        app.include_router(admin_compliance_reports_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_compliance_reports router: %s", e)
    # Admin chat tools (rules eval, policy, tickets)
    try:
        app.include_router(admin_chat_tools_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_chat_tools router: %s", e)
    # Custom BI endpoints used by the admin-react dashboard (no Grafana required)
    try:
        app.include_router(admin_bi_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_bi router: %s", e)
    # Tenant-scoped Party/account intelligence and human-governed identity proposals.
    try:
        from src.app.routers.admin_accounts import router as admin_accounts_router

        app.include_router(admin_accounts_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_accounts router: %s", e)
    # Escalation room (admin ↔ shopper chat stream per incident)
    try:
        app.include_router(escalation_room_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include escalation_room router: %s", e)
    # Public incident chat endpoints (token-protected, local-dev demo only)
    try:
        app.include_router(public_incidents_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include public_incidents router: %s", e)
    # Privacy-safe session events ingestion
    app.include_router(session_events_router)
    try:
        from src.app.routers.consumer_signals import router as consumer_signals_router
        app.include_router(consumer_signals_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include consumer_signals router: %s", e)
    try:
        from src.app.routers.decision_trace_events import router as decision_trace_events_router
        app.include_router(decision_trace_events_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include decision_trace_events router: %s", e)
    try:
        from src.app.routers.hippograph import router as hippograph_router
        app.include_router(hippograph_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include hippograph router: %s", e)
    try:
        from src.app.routers.decision_replay import router as decision_replay_router
        app.include_router(decision_replay_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include decision_replay router: %s", e)
    # Admin interleaving/budget summary endpoint
    try:
        from src.app.routers.admin_interleaving import router as admin_interleaving_router
        app.include_router(admin_interleaving_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_interleaving router: %s", e)
    # Admin interleaving static UI route (redirect to static page)
    try:
        from src.app.routers.admin_interleaving_ui import router as admin_interleaving_ui_router
        app.include_router(admin_interleaving_ui_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_interleaving_ui router: %s", e)
    # Job status endpoint for background workers
    try:
        from src.app.routers.jobs import router as jobs_router
        app.include_router(jobs_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include jobs router: %s", e)
    # Admin compliance registry endpoints (upload/list CI artifacts)
    try:
        from src.app.routers.admin_compliance_registry import router as admin_compliance_registry_router
        app.include_router(admin_compliance_registry_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_compliance_registry router: %s", e)
    # GRC risk register and report endpoints
    try:
        from src.app.routers.admin_grc import router as admin_grc_router
        app.include_router(admin_grc_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include admin_grc router: %s", e)
    # Include rules admin API (tenant-scoped rule management)
    try:
        from src.app.routers.rules import router as rules_router
        app.include_router(rules_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include rules router: %s", e)
    # Tenant-scoped config override API
    try:
        from src.app.routers.tenant_config import router as tenant_config_router
        app.include_router(tenant_config_router)
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to include tenant_config router: %s", e)
    # Serve local static assets (images, css, demo assets)
    try:
        static_dir = os.path.join(os.getcwd(), "static")
        if os.path.isdir(static_dir):
            app.mount("/static", StaticFiles(directory=static_dir), name="static")
    except Exception as e:
        import logging

        logging.getLogger("shopsquire.startup").exception("failed to mount static dir: %s", e)

    # Serve the built merchant/admin React UI from inside the repository so demo URLs
    # like `/merchant/dashboard` can show real BI + escalation consoles without
    # running a separate dev server.
    try:
        merchant_dist = os.path.join(os.getcwd(), "src", "frontend", "admin-react", "dist")
        if os.path.isdir(merchant_dist):
            app.mount("/merchant/app", StaticFiles(directory=merchant_dist, html=True), name="merchant_app")
            merchant_assets = os.path.join(merchant_dist, "assets")
            if os.path.isdir(merchant_assets):
                app.mount("/assets", StaticFiles(directory=merchant_assets), name="merchant_app_assets")
    except Exception:
        pass
    app.include_router(cart_router)
    from src.app.routers.cart_mutations import router as cart_mutations_router
    app.include_router(cart_mutations_router)   # C1: confirm-tier plan apply (V2 cart lane)
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

    # Inventory background worker — monitors stock levels and generates reorder recommendations.
    # Registered unconditionally; previously was erroneously inside the fraud router except block.
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
                        agent.generate_reorder_recommendations(alerts)
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

    # Start webhook dispatcher worker for persistent webhook delivery
    try:
        from src.app.services.webhook_dispatcher import start_worker, stop_worker

        webhook_worker_enabled = str(os.getenv("WEBHOOK_DISPATCHER_WORKER_ENABLED", "1")).lower() in ("1", "true", "yes")
        if webhook_worker_enabled:
            app.add_event_handler("startup", lambda: start_worker(app))
            app.add_event_handler("shutdown", stop_worker)
    except Exception:
        pass

    # DMARC poller (email security)
    try:
        from src.app.jobs.dmarc_poll import start_dmarc_poll, stop_dmarc_poll

        def _start_dmarc_worker():
            try:
                return start_dmarc_poll(app)
            except Exception:
                return None

        def _stop_dmarc_worker():
            try:
                stop_dmarc_poll(app)
            except Exception:
                pass

        app.add_event_handler("startup", _start_dmarc_worker)
        app.add_event_handler("shutdown", _stop_dmarc_worker)
    except Exception:
        pass
    # Fingerprint scanning worker for GRC alerts (headers/TLS/SSH)
    try:
        from src.app.services.grc_fingerprint import start_fingerprint_worker, stop_fingerprint_worker

        app.add_event_handler("startup", lambda: start_fingerprint_worker(app))
        app.add_event_handler("shutdown", lambda: stop_fingerprint_worker(app))
    except Exception:
        pass

    # Scheduled playbook DLQ reprocessor (safety-capped)
    try:
        from src.app.services.playbook_dlq_scheduler import start_dlq_scheduler, stop_dlq_scheduler

        app.add_event_handler("startup", lambda: start_dlq_scheduler(app))
        app.add_event_handler("shutdown", lambda: stop_dlq_scheduler(app))
    except Exception:
        pass

    # Scheduled playbook autorun engine (interval-based)
    try:
        from src.app.services.playbook_scheduler import start_playbook_scheduler, stop_playbook_scheduler

        app.add_event_handler("startup", lambda: start_playbook_scheduler(app))
        app.add_event_handler("shutdown", lambda: stop_playbook_scheduler(app))
    except Exception:
        pass

    # Incident SLA monitor (escalation room)
    try:
        from src.app.services.incident_sla_scheduler import start_incident_sla_scheduler, stop_incident_sla_scheduler

        app.add_event_handler("startup", lambda: start_incident_sla_scheduler(app))
        app.add_event_handler("shutdown", lambda: stop_incident_sla_scheduler(app))
    except Exception:
        pass

    # Money-P0 M1: payment-attempt reconciliation (transactional-outbox reader) — heals a lost
    # order↔intent association so a provider charge never orphans.
    try:
        from src.app.services.payment_reconcile_scheduler import (
            start_payment_reconcile_scheduler, stop_payment_reconcile_scheduler)
        app.add_event_handler("startup", lambda: start_payment_reconcile_scheduler(app))
        app.add_event_handler("shutdown", lambda: stop_payment_reconcile_scheduler(app))
    except Exception:
        pass

    # Automated SBOM correlation scheduler
    try:
        from src.app.services.sbom_scheduler import start_sbom_scheduler, stop_sbom_scheduler

        app.add_event_handler("startup", lambda: start_sbom_scheduler(app))
        app.add_event_handler("shutdown", lambda: stop_sbom_scheduler(app))
    except Exception:
        pass

    # Automated threat intel feed ingestion scheduler
    try:
        from src.app.services.threat_intel_scheduler import start_threat_intel_scheduler, stop_threat_intel_scheduler

        app.add_event_handler("startup", lambda: start_threat_intel_scheduler(app))
        app.add_event_handler("shutdown", lambda: stop_threat_intel_scheduler(app))
    except Exception:
        pass

    # Async phishing-page analysis worker for queued email landing-page jobs.
    try:
        from src.app.services.phishing_page_worker import start_phishing_page_worker, stop_phishing_page_worker

        app.add_event_handler("startup", lambda: start_phishing_page_worker(app))
        app.add_event_handler("shutdown", lambda: stop_phishing_page_worker(app))
    except Exception:
        pass

    # Scheduled URL re-check worker for deferred phishing detonation (T+15m/T+2h).
    try:
        from src.app.services.url_recheck_scheduler import start_url_recheck_scheduler, stop_url_recheck_scheduler

        app.add_event_handler("startup", lambda: start_url_recheck_scheduler(app))
        app.add_event_handler("shutdown", lambda: stop_url_recheck_scheduler(app))
    except Exception:
        pass

    # mTLS certificate expiry monitoring (alerts before certificate expiration)
    try:
        from src.app.services.mtls_cert_monitor import start_mtls_cert_monitor, stop_mtls_cert_monitor

        app.add_event_handler("startup", lambda: start_mtls_cert_monitor(app))
        app.add_event_handler("shutdown", lambda: stop_mtls_cert_monitor(app))
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


# Module-level app for uvicorn (e.g., uvicorn src.app.main:app)
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("API_HOST", "0.0.0.0"), port=int(os.getenv("API_PORT", "8080")))
