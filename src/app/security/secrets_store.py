from __future__ import annotations

import os
import json
from typing import Dict, Any

import requests


def _vault_conf() -> dict:
    return {
        "addr": os.getenv("VAULT_ADDR"),
        "token": os.getenv("VAULT_TOKEN"),
        "api_keys_path": os.getenv("VAULT_API_KEYS_PATH", "shopsquire/api_keys"),
    }


def _is_vault_enabled() -> bool:
    conf = _vault_conf()
    return bool(conf.get("addr") and conf.get("token"))


def _vault_get(path: str) -> dict | None:
    conf = _vault_conf()
    if not conf.get("addr") or not conf.get("token"):
        return None
    addr = conf["addr"].rstrip("/")
    token = conf["token"]
    # Try KV v2 first (/v1/secret/data/<path>) then fallback to v1 (/v1/secret/<path>)
    headers = {"X-Vault-Token": token}
    try:
        url = f"{addr}/v1/secret/data/{path}"
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            j = r.json()
            data = j.get("data", {})
            # KV v2 nests actual values under `data`
            if isinstance(data, dict) and "data" in data:
                return data.get("data")
            return data
    except Exception:
        pass
    try:
        url = f"{addr}/v1/secret/{path}"
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            j = r.json()
            return j.get("data") or j
    except Exception:
        pass
    return None


def fetch_api_keys() -> dict[str, list[dict[str, Any]]]:
    """Return a mapping of role -> list of key records from Vault if available.

    Each key record is expected to be an object with at least `key` and optional `label` and `created_at`.
    """
    if not _is_vault_enabled():
        return {}
    conf = _vault_conf()
    path = conf.get("api_keys_path") or "shopsquire/api_keys"
    try:
        data = _vault_get(path)
        if not data or not isinstance(data, dict):
            return {}
        # Vault may store nested structures; normalize to role -> list
        out: dict[str, list[dict[str, Any]]] = {}
        for role, vals in data.items():
            if isinstance(vals, list):
                out[role] = [v for v in vals if isinstance(v, dict)]
            elif isinstance(vals, dict):
                # single-record dict -> wrap
                out[role] = [vals]
        return out
    except Exception:
        return {}


def write_api_keys(payload: dict) -> bool:
    """Write the given payload into Vault at configured path. Returns True on success.

    This will attempt KV v2 then KV v1.
    """
    if not _is_vault_enabled():
        return False
    conf = _vault_conf()
    addr = conf["addr"].rstrip("/")
    token = conf["token"]
    path = conf.get("api_keys_path") or "shopsquire/api_keys"
    headers = {"X-Vault-Token": token, "Content-Type": "application/json"}
    try:
        url = f"{addr}/v1/secret/data/{path}"
        body = {"data": payload}
        r = requests.post(url, headers=headers, data=json.dumps(body), timeout=5)
        if r.status_code in (200, 204):
            return True
    except Exception:
        pass
    try:
        url = f"{addr}/v1/secret/{path}"
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        if r.status_code in (200, 204):
            return True
    except Exception:
        pass
    return False
