"""Simple HashiCorp Vault helper with env fallback.

This is a minimal safe helper: if `VAULT_ADDR` and `VAULT_TOKEN` are present,
we attempt to read a secret at the given path. Otherwise fall back to
`os.getenv(key)`.

We avoid adding hvac as a hard dependency; if hvac is present it will be used.
"""
from typing import Optional, Dict, Any
import os


def get_secret(path: str, key: Optional[str] = None) -> Optional[str]:
    """Return secret value for `path`. If `key` provided, returns that sub-key.
    Fallback to environment variables when Vault unavailable.
    """
    vault_addr = os.getenv("VAULT_ADDR")
    vault_token = os.getenv("VAULT_TOKEN")
    # If token/addr not set, fallback to env var naming convention
    env_key = (key or path).upper().replace("/", "_").replace("-", "_")
    if not vault_addr or not vault_token:
        return os.getenv(env_key)
    try:
        import hvac
    except Exception:
        return os.getenv(env_key)
    try:
        client = hvac.Client(url=vault_addr, token=vault_token)
        if not client.is_authenticated():
            return os.getenv(env_key)
        # Try KV v2 (common) then v1
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
        # If single key present and no key argument, return first value
        if len(data) == 1:
            return next(iter(data.values()))
        return None
    except Exception:
        return os.getenv(env_key)
