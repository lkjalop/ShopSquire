"""Feature flag loader with Vault/env/file fallback.

Provides `get_flag(name, default)` and `load_flags()` helpers.
"""
from typing import Any, Dict, Optional, Tuple
import os
import json
import time
from src.app.config import get_settings, load_feature_flags


def _get_secret(path: str, key: Optional[str] = None) -> Optional[str]:
    """Best-effort Vault helper with env fallback.

    Note: `src/app/config.py` is a module, so we cannot import `src.app.config.vault`
    as a package submodule without renaming. Keep this helper self-contained.
    """
    vault_addr = os.getenv("VAULT_ADDR")
    vault_token = os.getenv("VAULT_TOKEN")
    env_key = (key or path).upper().replace("/", "_").replace("-", "_")
    if not vault_addr or not vault_token:
        return os.getenv(env_key)
    try:
        import hvac  # type: ignore
    except Exception:
        return os.getenv(env_key)
    try:
        client = hvac.Client(url=vault_addr, token=vault_token)
        if not client.is_authenticated():
            return os.getenv(env_key)
        try:
            secret = client.secrets.kv.v2.read_secret_version(path=path)
            data = secret.get("data", {}).get("data", {})
        except Exception:
            try:
                secret = client.secrets.kv.v1.read_secret(path=path)
                data = secret.get("data", {})
            except Exception:
                data = {}
        if key:
            return data.get(key)
        if len(data) == 1:
            return next(iter(data.values()))
        return None
    except Exception:
        return os.getenv(env_key)


def load_flags() -> Dict[str, Any]:
    # First, attempt to load from Vault path if configured
    settings = get_settings()
    vault_path = os.getenv("FEATURE_FLAGS_VAULT_PATH")
    if vault_path:
        try:
            raw = _get_secret(vault_path)
            if raw:
                if isinstance(raw, str):
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        # Not JSON; ignore
                        pass
        except Exception:
            pass
    # Next fallback to disk-based feature flags via existing helper
    try:
        path = settings.feature_flags_path
        return load_feature_flags(path)
    except Exception:
        return {}


_FLAGS_CACHE: Optional[Dict[str, Any]] = None
_FLAGS_CACHE_META: Optional[Tuple[str, Optional[int], Optional[int]]] = None


def get_flags(force_reload: bool = False) -> Dict[str, Any]:
    """Return feature flags with lightweight drift detection.

    Many tests (and some local workflows) rewrite the feature-flags JSON file at runtime.
    If we cache forever, those writes won't take effect and test order becomes flaky.

    We reload when:
    - caller requests `force_reload`
    - the configured flags path changes
    - the flags file mtime changes
    """
    global _FLAGS_CACHE, _FLAGS_CACHE_META

    # In tests, feature flags are frequently rewritten; avoid order-dependent flakes.
    # (pytest sets PYTEST_CURRENT_TEST for each running test.)
    if os.getenv("PYTEST_CURRENT_TEST"):
        force_reload = True

    try:
        settings = get_settings()
        flags_path = settings.feature_flags_path
    except Exception:
        flags_path = os.getenv("FEATURE_FLAGS_PATH", "config/feature_flags.json")

    mtime_ns: Optional[int] = None
    size: Optional[int] = None
    try:
        if flags_path and os.path.exists(flags_path):
            st = os.stat(flags_path)
            mtime_ns = getattr(st, "st_mtime_ns", None) or int(st.st_mtime * 1_000_000_000)
            size = st.st_size
    except Exception:
        mtime_ns = None
        size = None

    if force_reload or _FLAGS_CACHE is None or _FLAGS_CACHE_META is None:
        _FLAGS_CACHE = load_flags()
        _FLAGS_CACHE_META = (flags_path, mtime_ns, size)
        return _FLAGS_CACHE

    cached_path, cached_mtime_ns, cached_size = _FLAGS_CACHE_META
    if cached_path != flags_path:
        _FLAGS_CACHE = load_flags()
        _FLAGS_CACHE_META = (flags_path, mtime_ns, size)
    elif mtime_ns is not None and cached_mtime_ns is not None and mtime_ns != cached_mtime_ns:
        _FLAGS_CACHE = load_flags()
        _FLAGS_CACHE_META = (flags_path, mtime_ns, size)
    elif size is not None and cached_size is not None and size != cached_size:
        _FLAGS_CACHE = load_flags()
        _FLAGS_CACHE_META = (flags_path, mtime_ns, size)

    # Very small safety valve: if the file clock resolution is coarse (e.g. fast rewrites),
    # allow tests to force reload via a short TTL env override.
    try:
        ttl = float(os.getenv("FEATURE_FLAGS_CACHE_TTL_SECONDS", "0") or "0")
    except Exception:
        ttl = 0.0
    if ttl > 0:
        now = time.time()
        # piggyback the meta mtime_ns slot as "last_load_time" when mtime is missing
        if mtime_ns is None:
            if cached_mtime_ns is None:
                _FLAGS_CACHE_META = (flags_path, int(now * 1_000_000_000), size)
            elif (now - (cached_mtime_ns / 1_000_000_000)) >= ttl:
                _FLAGS_CACHE = load_flags()
                _FLAGS_CACHE_META = (flags_path, int(now * 1_000_000_000), size)

    return _FLAGS_CACHE


def get_flag(name: str, default: Any = None) -> Any:
    # Allow env var override: e.g., YOLO_ROI_ENABLED=1
    env = os.getenv(name.upper())
    if env is not None:
        if env.strip().lower() in ("1", "true", "yes", "on"):
            return True
        if env.strip().lower() in ("0", "false", "no", "off"):
            return False
        return env
    flags = get_flags()
    return flags.get(name, default)
