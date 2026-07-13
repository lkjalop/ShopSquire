import json
import os
import time
from urllib.parse import urlparse
from dataclasses import dataclass
from functools import lru_cache
from src.app.services.secrets_manager import get_secret
from typing import Any

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


@dataclass
class Settings:
    app_env: str
    api_host: str
    api_port: int
    database_url: str
    redis_url: str
    stripe_api_key: str
    paypal_client_id: str
    paypal_client_secret: str
    llm_provider: str
    llm_model: str
    openai_api_key: str
    google_ai_api_key: str
    ollama_vision_model: str
    vuln_scan_enabled: bool
    vuln_scan_web_enabled: bool
    nuclei_templates_path: str
    fraud_graph_neo4j_enabled: bool
    vector_search_enabled: bool
    gnn_model_path: str
    feature_flags_path: str


def _secrets_strict_mode() -> bool:
    env = str(os.getenv("APP_ENV", "") or "").lower()
    explicit = str(os.getenv("SECRETS_PROVIDER_STRICT", "") or "").lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    return env in ("prod", "production")


def _resolved_secret(name: str, default: str) -> str:
    val = get_secret(name, default)
    if val not in (None, ""):
        return str(val)
    if _secrets_strict_mode():
        raise RuntimeError(f"missing_required_secret:{name}")
    return str(os.getenv(name, default))


def _settings_env_sig() -> tuple:
    # Include env vars that affect settings so cache entries are keyed on current env.
    return (
        os.getenv("APP_ENV"),
        os.getenv("API_HOST"),
        os.getenv("API_PORT"),
        os.getenv("DATABASE_URL"),
        os.getenv("REDIS_URL"),
        os.getenv("STRIPE_API_KEY"),
        os.getenv("STRIPE_API_KEY_REF"),
        os.getenv("PAYPAL_CLIENT_ID"),
        os.getenv("PAYPAL_CLIENT_ID_REF"),
        os.getenv("PAYPAL_CLIENT_SECRET"),
        os.getenv("PAYPAL_CLIENT_SECRET_REF"),
        os.getenv("LLM_PROVIDER"),
        os.getenv("LLM_MODEL"),
        os.getenv("OPENAI_API_KEY"),
        os.getenv("OPENAI_API_KEY_REF"),
        os.getenv("GOOGLE_AI_API_KEY"),
        os.getenv("GOOGLE_AI_API_KEY_REF"),
        os.getenv("OLLAMA_VISION_MODEL"),
        os.getenv("VULN_SCAN_ENABLED"),
        os.getenv("VULN_SCAN_WEB_ENABLED"),
        os.getenv("NUCLEI_TEMPLATES_PATH"),
        os.getenv("FRAUD_GRAPH_NEO4J_ENABLED"),
        os.getenv("VECTOR_SEARCH_ENABLED"),
        os.getenv("GNN_MODEL_PATH"),
        os.getenv("SECRETS_PROVIDER"),
        os.getenv("VAULT_ADDR"),
        os.getenv("AWS_REGION"),
        os.getenv("FEATURE_FLAGS_PATH"),
    )


def _default_database_url() -> str:
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    if env in ("local", "dev", "development", "test"):
        # Local default should be self-contained and deterministic when DATABASE_URL
        # is not explicitly configured.
        return "sqlite:///test.sqlite"
    return "postgresql+psycopg2://postgres:postgres@localhost:5432/shopsquire"


def _redis_url_has_auth(redis_url: str) -> bool:
    try:
        p = urlparse(str(redis_url or ""))
        return bool((p.password or "").strip())
    except Exception:
        return False


def _redis_url_is_tls(redis_url: str) -> bool:
    try:
        p = urlparse(str(redis_url or ""))
        return str(p.scheme or "").lower() in ("rediss",)
    except Exception:
        return False


def _is_non_dev_env(env: str | None) -> bool:
    e = str(env or "local").strip().lower()
    return e not in ("local", "dev", "development", "test", "testing")


def _is_truthy_env(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default) or default).strip().lower() in ("1", "true", "yes", "on")


@lru_cache(maxsize=8)
def _get_settings_cached(_sig: tuple) -> Settings:
    s = Settings(
        app_env=os.getenv("APP_ENV", "local"),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8080")),
        database_url=_resolved_secret("DATABASE_URL", _default_database_url()),
        redis_url=_resolved_secret("REDIS_URL", "redis://localhost:6379/0"),
        stripe_api_key=_resolved_secret("STRIPE_API_KEY", ""),
        paypal_client_id=_resolved_secret("PAYPAL_CLIENT_ID", ""),
        paypal_client_secret=_resolved_secret("PAYPAL_CLIENT_SECRET", ""),
        llm_provider=os.getenv("LLM_PROVIDER", "none"),
        llm_model=os.getenv("LLM_MODEL", ""),
        openai_api_key=_resolved_secret("OPENAI_API_KEY", ""),
        google_ai_api_key=_resolved_secret("GOOGLE_AI_API_KEY", ""),
        ollama_vision_model=os.getenv("OLLAMA_VISION_MODEL", "").strip(),
        vuln_scan_enabled=_is_truthy_env("VULN_SCAN_ENABLED", "1"),
        vuln_scan_web_enabled=_is_truthy_env("VULN_SCAN_WEB_ENABLED", "0"),
        nuclei_templates_path=os.getenv("NUCLEI_TEMPLATES_PATH", "").strip(),
        fraud_graph_neo4j_enabled=_is_truthy_env("FRAUD_GRAPH_NEO4J_ENABLED", "0"),
        vector_search_enabled=_is_truthy_env("VECTOR_SEARCH_ENABLED", "0"),
        gnn_model_path=os.getenv("GNN_MODEL_PATH", "config/gnn_model.pt").strip(),
        feature_flags_path=os.getenv("FEATURE_FLAGS_PATH", "config/feature_flags.json"),
    )
    # Enforce Stripe live key in non-dev environments.
    if _is_non_dev_env(s.app_env):
        stripe_key = str(s.stripe_api_key or "").strip()
        if not stripe_key or stripe_key.startswith("sk_test_"):
            raise RuntimeError("insecure_runtime:STRIPE_API_KEY_must_be_live_key_in_production")
    # Enforce Redis auth/TLS in non-dev environments.
    if _is_non_dev_env(s.app_env):
        if not _redis_url_has_auth(s.redis_url):
            raise RuntimeError("missing_required_secret:REDIS_URL_password")
        require_tls = str(os.getenv("REDIS_REQUIRE_TLS", "1")).strip().lower() in ("1", "true", "yes", "on")
        if require_tls and not _redis_url_is_tls(s.redis_url):
            raise RuntimeError("insecure_runtime:REDIS_URL_requires_rediss")
        # Infra/Data profile: enforce at-rest encryption + retention + immutable audit export.
        if not _is_truthy_env("PG_ENCRYPTION_AT_REST", "1"):
            raise RuntimeError("insecure_runtime:PG_ENCRYPTION_AT_REST_required")
        if not _is_truthy_env("RETENTION_CLEANUP_ENABLED", "1"):
            raise RuntimeError("insecure_runtime:RETENTION_CLEANUP_ENABLED_required")
        anchor_mode = str(os.getenv("AUDIT_CHAIN_EXTERNAL_ANCHOR_MODE", "none") or "none").strip().lower()
        if anchor_mode in ("", "none", "off", "disabled"):
            raise RuntimeError("insecure_runtime:AUDIT_CHAIN_EXTERNAL_ANCHOR_MODE_required")
        has_backup_key = bool(str(os.getenv("BACKUP_ENCRYPTION_KEY", "") or "").strip() or str(os.getenv("BACKUP_ENCRYPTION_PASSPHRASE", "") or "").strip())
        if not has_backup_key:
            raise RuntimeError("missing_required_secret:BACKUP_ENCRYPTION_KEY_or_PASSPHRASE")
    return s


def get_settings() -> Settings:
    return _get_settings_cached(_settings_env_sig())


# Expose cache_clear for tests that call get_settings.cache_clear()
try:
    get_settings.cache_clear = _get_settings_cached.cache_clear  # type: ignore[attr-defined]
except Exception:
    pass


def canonical_runtime_contract() -> dict[str, Any]:
    """Canonical runtime env contract used by `/readyz` config reporting."""
    s = get_settings()
    api_base = os.getenv("API_BASE_URL", "").strip()
    if not api_base:
        host = (s.api_host or "127.0.0.1").strip()
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        api_base = f"http://{host}:{int(s.api_port)}"
    return {
        "API_BASE_URL": api_base,
        "API_PORT": int(s.api_port),
        "DATABASE_URL": str(s.database_url or "").strip(),
        "REDIS_URL": str(s.redis_url or "").strip(),
        "FEATURE_FLAGS_PATH": str(s.feature_flags_path or "").strip(),
        "GOOGLE_AI_API_KEY": str(s.google_ai_api_key or "").strip(),
        "OLLAMA_VISION_MODEL": str(s.ollama_vision_model or "").strip(),
        "VULN_SCAN_ENABLED": bool(s.vuln_scan_enabled),
        "VULN_SCAN_WEB_ENABLED": bool(s.vuln_scan_web_enabled),
        "NUCLEI_TEMPLATES_PATH": str(s.nuclei_templates_path or "").strip(),
        "FRAUD_GRAPH_NEO4J_ENABLED": bool(s.fraud_graph_neo4j_enabled),
        "VECTOR_SEARCH_ENABLED": bool(s.vector_search_enabled),
        "GNN_MODEL_PATH": str(s.gnn_model_path or "").strip(),
        "MERCHANT_API_KEY": str(os.getenv("MERCHANT_API_KEY", "")).strip(),
        "OWNER_API_KEY": str(os.getenv("OWNER_API_KEY", "")).strip(),
        "DEVELOPER_API_KEY": str(os.getenv("DEVELOPER_API_KEY", "")).strip(),
    }


def validate_runtime_contract() -> dict[str, Any]:
    contract = canonical_runtime_contract()
    required = ["API_BASE_URL", "API_PORT", "DATABASE_URL", "REDIS_URL", "FEATURE_FLAGS_PATH"]
    missing = [k for k in required if not contract.get(k)]
    warnings: list[str] = []
    if str(contract.get("API_PORT")) != "8080":
        warnings.append("API_PORT_noncanonical_expected_8080")
    for key in ("MERCHANT_API_KEY", "OWNER_API_KEY", "DEVELOPER_API_KEY"):
        if not contract.get(key):
            warnings.append(f"{key}_not_set_using_defaults_or_auth_failures_possible")
    env = str(os.getenv("APP_ENV", "local") or "local").lower()
    if _is_non_dev_env(env) and not _redis_url_has_auth(str(contract.get("REDIS_URL") or "")):
        warnings.append("REDIS_URL_missing_password_for_production")
    if _is_non_dev_env(env):
        require_tls = str(os.getenv("REDIS_REQUIRE_TLS", "1")).strip().lower() in ("1", "true", "yes", "on")
        if require_tls and not _redis_url_is_tls(str(contract.get("REDIS_URL") or "")):
            warnings.append("REDIS_URL_missing_tls_rediss_scheme")
        if not str(os.getenv("REDIS_ACL_USERNAME", "") or "").strip():
            warnings.append("REDIS_ACL_USERNAME_not_set")
        if not str(os.getenv("REDIS_ACL_PASSWORD", "") or "").strip():
            warnings.append("REDIS_ACL_PASSWORD_not_set")
    return {
        "ok": len(missing) == 0,
        "missing": missing,
        "warnings": warnings,
        "contract": contract,
    }


def load_feature_flags(path: str) -> dict:
    def _env_bool(name: str) -> bool | None:
        raw = os.getenv(name)
        if raw is None:
            return None
        s = str(raw).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
            return False
        return None

    def _apply_toggle_overrides(flags: dict) -> dict:
        """ENV WINS for every flag (the 9th-mute-layer class fix, 2026-07-09): this loader used
        to merge exactly ONE env override, so a gate reading the flags dict never saw env-set
        toggles — HIPPOGRAPH_FEEDBACK_ENABLED=shadow via start_demo/harness/docker silently
        never reached _mi_mode and market intelligence was OFF in every live run of the arc.
        Rule: any TOP-LEVEL SCALAR key present in the flags file, plus the curated runtime
        gates below (modes that ship env-only, absent from the file), is overridable by an
        identically-named env var. Values stay strings — every consumer already parses via
        str(v).lower()/_safe_int, and env is the ops override channel platform-wide."""
        out = dict(flags or {})
        _RUNTIME_GATES = (
            "HIPPOGRAPH_FEEDBACK_ENABLED", "HIPPOGRAPH_CATALOG_EDGES",
            "MARKET_ANALYSIS_ENABLED", "MARKET_PIPELINE_ENABLED",
            "MARKET_EVIDENCE_IN_NARRATION",
            "STOREFRONT_EMPHASIS_EXPERIMENT_ENABLED", "STOREFRONT_EMPHASIS_CANARY_FRACTION",
            "STOREFRONT_EMPHASIS_EXPERIMENT_ID",
            "RANKING_NUDGE_EXPERIMENT_ENABLED", "RANKING_NUDGE_CANARY_FRACTION",
            "SALES_RESPONSE_NUDGE_ENABLED",
            "RECOMMEND_NARRATION_MODE", "RECOMMEND_NARRATION_FORCE",
        )
        candidates = {k for k in out if isinstance(out.get(k), (str, bool, int, float))}
        candidates.update(_RUNTIME_GATES)
        for key in candidates:
            v = os.getenv(key)
            if v is None or str(v).strip() == "":
                continue
            cur = out.get(key)
            # TYPE-COERCE to the file value's type (live incident 2026-07-09: an ambient
            # KILL_SWITCH='false' env string replaced the file's boolean False, and the autonomy
            # governor's truthiness check read the non-empty string as ENGAGED — every recommend
            # request 503'd. A bool flag must never become a string.)
            if isinstance(cur, bool):
                b = _env_bool(key)
                if b is not None:
                    out[key] = b
            elif isinstance(cur, int) and not isinstance(cur, bool):
                try:
                    out[key] = int(str(v).strip())
                except ValueError:
                    pass
            elif isinstance(cur, float):
                try:
                    out[key] = float(str(v).strip())
                except ValueError:
                    pass
            else:  # string file values + runtime gates absent from the file (consumers parse)
                out[key] = v
        return out

    def _defaults() -> dict:
        # Sensible defaults when feature flags file is missing:
        # - Enable decision log writes by default in non-production environments
        # - Allow explicit override via environment variable `DECISION_LOG_WRITES_ENABLED`
        settings = get_settings()
        env_override = os.getenv("DECISION_LOG_WRITES_ENABLED")
        if env_override is not None:
            try:
                decision_writes = env_override.strip() in ("1", "true", "True", "yes", "on")
            except Exception:
                decision_writes = False
        else:
            # Enable by default unless running in production
            decision_writes = settings.app_env.lower() not in ("production", "prod")
        return {
            "USE_AGENT_CAPABILITIES": True,
            "AGENT_ROLLOUT_PERCENT": 20,
            "CAPABILITIES": {
                "pricing": {"enabled": True, "rollout_percent": 20},
                "support": {"enabled": False, "rollout_percent": 0},
                "inventory": {"enabled": False, "rollout_percent": 0},
                "recommend": {"enabled": True, "rollout_percent": 20},
                "paypal": {"enabled": False, "rollout_percent": 0},
                "revolut": {"enabled": False, "rollout_percent": 0},
                "googlepay": {"enabled": False, "rollout_percent": 0},
                "afterpay": {"enabled": False, "rollout_percent": 0},
            },
            "KILL_SWITCH": False,
            "AUTONOMY": {
                "kill_switch": False,
                "reason": "",
                "scopes": {
                    "recommend": {"disabled": False, "reason": ""},
                    "pricing": {"disabled": False, "reason": ""},
                    "payments": {"disabled": False, "reason": ""},
                    "support": {"disabled": False, "reason": ""},
                    "inventory": {"disabled": False, "reason": ""},
                    "incident": {"disabled": False, "reason": ""},
                    "email_security": {"disabled": False, "reason": ""},
                    "orchestrator": {"disabled": False, "reason": ""},
                },
            },
            "DECISION_LOG_WRITES_ENABLED": decision_writes,
            # In test/local mode, allow bypassing strict policy gate to keep
            # end-to-end smoke tests deterministic. Can be overridden via
            # FEATURE_FLAGS file or the TEST_BYPASS_POLICY_GATE env var.
            "TEST_BYPASS_POLICY_GATE": settings.app_env.lower() not in ("production", "prod"),
            "POLICY_VERSION": "v1",
            "DEGRADATION": {
                "enabled": True,
                "window_seconds": 300,
                "min_requests": 10,
                "error_rate_threshold": 0.2,
                "open_seconds": 120,
                "force_rules": False,
            },
            "CHAOS": {
                "enabled": False,
                "latency_ms": 0,
                "probability": 0.0,
            },
            "RAGAS_EVAL_ENABLED": False,
            "TEST_FORCE_BAD_SKU": False,
            "SECURITY_THRESHOLDS": {
                "ML_DECISION_GATE": {
                    "enabled": True,
                    "LEARNED_ML_GATE_ENABLED": True,
                    "LEARNED_ML_GATE_TENANT_ALLOWLIST": [],
                    "LEARNED_ML_GATE_CANARY_PERCENT": 100,
                    "SHADOW_MODE_ENABLED": False,
                    "allow_threshold": 0.35,
                    "block_threshold": 0.7,
                    "POLICY_TARGETS": {
                        "allow_false_negative_ceiling": 0.03,
                        "block_false_positive_ceiling": 0.02,
                        "review_queue_max": 200,
                        "review_sla_minutes": 30,
                    },
                }
            },
        }

    def _deep_merge(base: dict, override: dict) -> dict:
        out = dict(base)
        for k, v in (override or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = _deep_merge(out.get(k, {}), v)
            else:
                out[k] = v
        return out

    defaults = _defaults()
    # Always honor the current environment variable to avoid cached settings
    # leaking across test modules.
    # If env var is set, honor it. Otherwise, choose the most recently updated
    # feature flags file between the passed path and the repo default to avoid
    # cached settings paths leaking across tests.
    env_path = os.getenv("FEATURE_FLAGS_PATH")
    if env_path:
        effective_path = env_path
    else:
        default_path = "config/feature_flags.json"
        candidates = []
        if path:
            candidates.append(path)
        candidates.append(default_path)
        # Pick the most recently modified existing file. Ignore stale temp paths.
        best_path = default_path
        best_mtime = -1
        now_ts = time.time()
        for p in candidates:
            try:
                if os.path.exists(p):
                    mtime = os.path.getmtime(p)
                    # Heuristic: ignore temp/pytest paths unless updated very recently.
                    if p != default_path:
                        low = p.lower()
                        if ("pytest" in low or "tmp" in low or "temp" in low) and (now_ts - mtime) > 10:
                            continue
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best_path = p
            except Exception:
                continue
        effective_path = best_path
    try:
        # Read as bytes first to handle UTF-8 BOM and optionally self-heal in dev.
        raw_bytes = None
        try:
            with open(effective_path, "rb") as bf:
                raw_bytes = bf.read()
        except Exception:
            raw_bytes = None

        if raw_bytes is not None:
            has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
            text = raw_bytes.decode("utf-8-sig")
            loaded = json.loads(text)
            if not isinstance(loaded, dict):
                return defaults
            merged = _deep_merge(defaults, loaded)
            # DECISION-AUDIT DEFAULT (P1-1): the bitemporal decision log is the product differentiator,
            # so it defaults ON in EVERY environment when the env var is unset — previously it was
            # forced on only in NON-production, so a real prod deploy silently fell to the shipped
            # flag (false) and the audit trail was dark exactly where it matters (dev could never
            # catch it). Operators disable explicitly with DECISION_LOG_WRITES_ENABLED=0 (e.g. a
            # compliance hold until the DPA is signed — see policy/data_residency.py / P1-2).
            try:
                if os.getenv("DECISION_LOG_WRITES_ENABLED") is None:
                    merged["DECISION_LOG_WRITES_ENABLED"] = True
                    if get_settings().app_env.lower() in ("production", "prod"):
                        import logging
                        logging.getLogger("shopsquire.config").info(
                            "DECISION_LOG_WRITES_ENABLED defaulted ON in production (audit differentiator); "
                            "set DECISION_LOG_WRITES_ENABLED=0 to disable deliberately.")
            except Exception:
                import logging

                logging.getLogger("shopsquire.config").exception("Failed merging feature flags from effective path")
            # If BOM detected, rewrite without BOM in dev to prevent silent flag drift.
            try:
                if has_bom and get_settings().app_env.lower() not in ("production", "prod"):
                    with open(effective_path, "w", encoding="utf-8") as wf:
                        json.dump(loaded, wf, ensure_ascii=False)
            except Exception:
                pass
            return _apply_toggle_overrides(merged)

        with open(effective_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if not isinstance(loaded, dict):
                return defaults
            merged = _deep_merge(defaults, loaded)
            try:
                if os.getenv("DECISION_LOG_WRITES_ENABLED") is None:
                    if get_settings().app_env.lower() not in ("production", "prod"):
                        merged["DECISION_LOG_WRITES_ENABLED"] = True
            except Exception:
                pass
            return _apply_toggle_overrides(merged)
    except Exception:
        # If the configured path is missing (e.g. temp file in tests),
        # fall back to the default project feature flags file.
        try:
            fallback_path = "config/feature_flags.json"
            if effective_path != fallback_path and os.path.exists(fallback_path):
                with open(fallback_path, "rb") as f:
                    raw = f.read()
                loaded = json.loads(raw.decode("utf-8-sig"))
                if isinstance(loaded, dict):
                    merged = _deep_merge(defaults, loaded)
                    try:
                        if os.getenv("DECISION_LOG_WRITES_ENABLED") is None:
                            if get_settings().app_env.lower() not in ("production", "prod"):
                                merged["DECISION_LOG_WRITES_ENABLED"] = True
                    except Exception:
                        import logging

                        logging.getLogger("shopsquire.config").exception("Failed checking DECISION_LOG_WRITES_ENABLED env logic")
                    return _apply_toggle_overrides(merged)
        except Exception:
            import logging

            logging.getLogger("shopsquire.config").exception("Failed loading fallback feature flags file")
        return _apply_toggle_overrides(defaults)
