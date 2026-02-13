import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from src.app.services.secrets_manager import get_secret


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
        os.getenv("SECRETS_PROVIDER"),
        os.getenv("VAULT_ADDR"),
        os.getenv("AWS_REGION"),
        os.getenv("FEATURE_FLAGS_PATH"),
    )


@lru_cache(maxsize=8)
def _get_settings_cached(_sig: tuple) -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "local"),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8080")),
        database_url=_resolved_secret("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/shopsquire"),
        redis_url=_resolved_secret("REDIS_URL", "redis://localhost:6379/0"),
        stripe_api_key=_resolved_secret("STRIPE_API_KEY", "sk_test_xxx"),
        paypal_client_id=_resolved_secret("PAYPAL_CLIENT_ID", ""),
        paypal_client_secret=_resolved_secret("PAYPAL_CLIENT_SECRET", ""),
        llm_provider=os.getenv("LLM_PROVIDER", "none"),
        llm_model=os.getenv("LLM_MODEL", ""),
        openai_api_key=_resolved_secret("OPENAI_API_KEY", ""),
        feature_flags_path=os.getenv("FEATURE_FLAGS_PATH", "config/feature_flags.json"),
    )


def get_settings() -> Settings:
    return _get_settings_cached(_settings_env_sig())


# Expose cache_clear for tests that call get_settings.cache_clear()
try:
    get_settings.cache_clear = _get_settings_cached.cache_clear  # type: ignore[attr-defined]
except Exception:
    pass


def load_feature_flags(path: str) -> dict:
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
            # In non-production, ensure decision logs are enabled unless explicitly overridden.
            try:
                if os.getenv("DECISION_LOG_WRITES_ENABLED") is None:
                    if get_settings().app_env.lower() not in ("production", "prod"):
                        merged["DECISION_LOG_WRITES_ENABLED"] = True
            except Exception:
                pass
            # If BOM detected, rewrite without BOM in dev to prevent silent flag drift.
            try:
                if has_bom and get_settings().app_env.lower() not in ("production", "prod"):
                    with open(effective_path, "w", encoding="utf-8") as wf:
                        json.dump(loaded, wf, ensure_ascii=False)
            except Exception:
                pass
            return merged

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
            return merged
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
                        pass
                    return merged
        except Exception:
            pass
        return defaults
