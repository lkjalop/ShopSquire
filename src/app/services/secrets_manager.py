from __future__ import annotations

import os
import time
from typing import Optional

_CACHE: dict[str, tuple[float, Optional[str]]] = {}


def _is_strict_provider_mode() -> bool:
    env = str(os.getenv("APP_ENV", "") or "").lower()
    explicit = str(os.getenv("SECRETS_PROVIDER_STRICT", "") or "").lower()
    if explicit in ("1", "true", "yes", "on"):
        return True
    return env in ("prod", "production")


def _cache_ttl() -> int:
    try:
        return max(1, int(os.getenv("SECRETS_CACHE_TTL_SEC", "60") or 60))
    except Exception:
        return 60


def _cache_get(key: str) -> Optional[str]:
    now = time.time()
    item = _CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if now - ts > float(_cache_ttl()):
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: Optional[str]) -> Optional[str]:
    _CACHE[key] = (time.time(), value)
    return value


def _env_fallback(name: str, default: str | None = None) -> str | None:
    if _is_strict_provider_mode():
        allow_env = str(os.getenv("SECRETS_ALLOW_ENV_REF_IN_STRICT", "") or "").lower() in ("1", "true", "yes", "on")
        if not allow_env:
            return default
    v = os.getenv(name)
    if v is not None and str(v) != "":
        return v
    return default


def _vault_get(path: str, key: Optional[str] = None) -> Optional[str]:
    vault_addr = os.getenv("VAULT_ADDR")
    vault_token = os.getenv("VAULT_TOKEN")
    if not vault_addr or not vault_token:
        return None
    try:
        import hvac  # type: ignore
    except Exception:
        return None
    try:
        client = hvac.Client(url=vault_addr, token=vault_token)
        if not client.is_authenticated():
            return None
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
        return None


def _aws_sm_get(secret_id: str, key: Optional[str] = None) -> Optional[str]:
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not region:
        return None
    try:
        from src.app.providers.aws import get_secret_value
    except Exception:
        return None
    try:
        res = get_secret_value(secret_id, region)
        sval = res.get("SecretString")
        if sval is None:
            return None
        if key:
            try:
                import json

                obj = json.loads(sval)
                if isinstance(obj, dict):
                    return obj.get(key)
            except Exception:
                return None
        return sval
    except Exception:
        return None


def _azure_kv_get(
    vault_name: str,
    secret_name: str,
    version: Optional[str] = None,
) -> Optional[str]:
    """Resolve a Key Vault secret through workload identity/default credentials."""
    try:
        from src.app.providers.azure import get_key_vault_secret
    except Exception:
        return None
    vault = str(vault_name or "").strip()
    if not vault or not secret_name:
        return None
    vault_url = vault if vault.startswith("https://") else f"https://{vault}.vault.azure.net"
    try:
        return get_key_vault_secret(vault_url, secret_name, version)
    except Exception:
        return None


def _parse_secret_ref(value: str) -> tuple[str, str, Optional[str]]:
    # Supported:
    # vault://path#key
    # aws-sm://secret-id#key
    # azure-kv://vault-name/secret-name#version
    # env://ENV_VAR_NAME
    raw = str(value or "")
    if "://" not in raw:
        return ("env", raw, None)
    scheme, rest = raw.split("://", 1)
    if "#" in rest:
        locator, key = rest.split("#", 1)
        return (scheme.lower(), locator, key or None)
    return (scheme.lower(), rest, None)


def resolve_secret(value_or_ref: str | None, *, default: str | None = None) -> str | None:
    if not value_or_ref:
        return default
    raw = str(value_or_ref)
    if "://" not in raw:
        return raw
    # Only treat a value as a secret reference when it uses a supported scheme.
    # This prevents accidentally interpreting ordinary URIs (e.g. `postgresql://`,
    # `redis://`, `https://`) as secret references and falling back to defaults.
    scheme = raw.split("://", 1)[0].lower()
    if scheme not in (
        "vault",
        "aws-sm",
        "aws-secretsmanager",
        "azure-kv",
        "azure-keyvault",
        "env",
    ):
        return raw
    cache_key = f"ref:{raw}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    scheme, locator, key = _parse_secret_ref(raw)
    out: Optional[str] = None
    if scheme == "vault":
        out = _vault_get(locator, key)
    elif scheme in ("aws-sm", "aws-secretsmanager"):
        out = _aws_sm_get(locator, key)
    elif scheme in ("azure-kv", "azure-keyvault"):
        vault_name, separator, secret_name = locator.partition("/")
        if separator:
            out = _azure_kv_get(vault_name, secret_name, key)
    elif scheme == "env":
        out = _env_fallback(locator, default)
    if out is None:
        out = default
    return _cache_put(cache_key, out)


def get_secret(name: str, default: str | None = None) -> str | None:
    # Supports:
    # - plain env value
    # - NAME_REF env pointing to vault:// / aws-sm:// / env:// references
    # - provider-backed retrieval by naming convention if provider enabled
    cache_key = f"name:{name}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    ref = os.getenv(f"{name}_REF")
    if ref:
        return _cache_put(cache_key, resolve_secret(ref, default=default))

    direct = os.getenv(name)
    if direct not in (None, ""):
        # if direct itself is a reference, resolve it
        if _is_strict_provider_mode() and "://" not in str(direct):
            # In production strict mode, raw inline secrets are disallowed.
            return _cache_put(cache_key, default)
        resolved = resolve_secret(direct, default=default)
        return _cache_put(cache_key, resolved)

    provider = str(os.getenv("SECRETS_PROVIDER", "env") or "env").lower()
    out: Optional[str] = None
    if provider == "vault":
        base = os.getenv("SECRETS_VAULT_BASE_PATH", "kv/shopsquire")
        out = _vault_get(f"{base}/{name.lower()}", None)
    elif provider in ("aws-sm", "aws-secretsmanager"):
        prefix = os.getenv("SECRETS_AWS_PREFIX", "shopsquire/")
        out = _aws_sm_get(f"{prefix}{name}", None)
    elif provider in ("azure-kv", "azure-keyvault"):
        vault_name = os.getenv("SECRETS_AZURE_VAULT_NAME", "")
        prefix = os.getenv("SECRETS_AZURE_PREFIX", "")
        out = _azure_kv_get(vault_name, f"{prefix}{name.lower()}", None)
    if out is None:
        out = default
    return _cache_put(cache_key, out)


def get_secret_required(name: str, *, default: str | None = None) -> str:
    val = get_secret(name, default=default)
    if val not in (None, ""):
        return str(val)
    if _is_strict_provider_mode():
        raise RuntimeError(f"required_secret_unavailable:{name}")
    return str(default or "")
