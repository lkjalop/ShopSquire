"""Tenant registry for StoreProfile and future connector routing.

This is the request-boundary security layer above StoreProfile selection:
tenants may only activate profiles explicitly assigned to them. With no
registry configured, dev/demo behavior remains unchanged so local profile
experiments can still use X-Store-Profile directly.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

_REGISTRY_JSON_ENV = "STORE_TENANT_REGISTRY_JSON"
_REGISTRY_PATH_ENV = "STORE_TENANT_REGISTRY_PATH"


@dataclass(frozen=True)
class StoreProfileResolution:
    tenant_id: Optional[str]
    profile_id: Optional[str]
    allowed: bool
    reason: Optional[str] = None
    registry_enabled: bool = False


def _clean_id(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _clean_profile(value: Any) -> Optional[str]:
    text = _clean_id(value)
    return text.lower() if text else None


def _registry_source_text() -> Optional[str]:
    inline = os.getenv(_REGISTRY_JSON_ENV)
    if inline and inline.strip():
        return inline
    path = os.getenv(_REGISTRY_PATH_ENV)
    if path and path.strip():
        return Path(path).read_text(encoding="utf-8")
    return None


@lru_cache(maxsize=1)
def _load_registry() -> Dict[str, Dict[str, Any]]:
    raw = _registry_source_text()
    if not raw:
        return {}
    data = json.loads(raw)
    if isinstance(data, dict) and isinstance(data.get("tenants"), dict):
        data = data["tenants"]
    if not isinstance(data, dict):
        raise ValueError("tenant registry must be an object or {'tenants': {...}}")

    out: Dict[str, Dict[str, Any]] = {}
    for tenant_id, cfg in data.items():
        tid = _clean_id(tenant_id)
        if not tid or not isinstance(cfg, dict):
            continue
        default_profile = _clean_profile(
            cfg.get("store_profile_id") or cfg.get("profile_id") or cfg.get("profile")
        )
        allowed_raw = cfg.get("allowed_profiles") or cfg.get("profiles") or []
        if isinstance(allowed_raw, str):
            allowed = [_clean_profile(allowed_raw)]
        else:
            allowed = [_clean_profile(v) for v in list(allowed_raw or [])]
        allowed = [v for v in allowed if v]
        if default_profile and default_profile not in allowed:
            allowed.insert(0, default_profile)
        out[tid] = {
            "store_profile_id": default_profile,
            "allowed_profiles": allowed,
            # Reserved for Phase 3 ports. Keeping these normalized here prevents
            # another tenant config parser from growing beside this one.
            "connectors": cfg.get("connectors") if isinstance(cfg.get("connectors"), dict) else {},
            "consent_policy": cfg.get("consent_policy") if isinstance(cfg.get("consent_policy"), dict) else {},
        }
    return out


def registry_enabled() -> bool:
    inline = os.getenv(_REGISTRY_JSON_ENV)
    path = os.getenv(_REGISTRY_PATH_ENV)
    return bool((inline and inline.strip()) or (path and path.strip()))


def reset_cache() -> None:
    try:
        _load_registry.cache_clear()
    except Exception:
        pass


def tenant_config(tenant_id: Optional[str]) -> Dict[str, Any]:
    """Return one tenant config, or {} when the registry is disabled/missing."""
    if not registry_enabled():
        return {}
    tid = _clean_id(tenant_id) or "default"
    try:
        return dict(_load_registry().get(tid) or {})
    except Exception:
        return {}


def resolve_store_profile_for_request(
    *,
    tenant_id: Optional[str],
    requested_profile_id: Optional[str],
) -> StoreProfileResolution:
    """Resolve the active StoreProfile for a request.

    Without a tenant registry, the middleware preserves existing demo behavior:
    an X-Store-Profile header may select any profile and STORE_PROFILE_ID/env
    remains the fallback. Once a registry is configured, tenant/profile mismatch
    fails closed before request handlers run.
    """
    requested = _clean_profile(requested_profile_id)
    tid = _clean_id(tenant_id)
    if not registry_enabled():
        return StoreProfileResolution(
            tenant_id=tid,
            profile_id=requested,
            allowed=True,
            registry_enabled=False,
        )

    try:
        registry = _load_registry()
    except Exception:
        return StoreProfileResolution(
            tenant_id=tid or "default",
            profile_id=requested,
            allowed=False,
            reason="tenant_registry_invalid",
            registry_enabled=True,
        )
    effective_tenant = tid or "default"
    cfg = registry.get(effective_tenant)
    if not cfg:
        return StoreProfileResolution(
            tenant_id=effective_tenant,
            profile_id=requested,
            allowed=False,
            reason="unknown_tenant",
            registry_enabled=True,
        )

    default_profile = _clean_profile(cfg.get("store_profile_id"))
    profile = requested or default_profile
    if not profile:
        return StoreProfileResolution(
            tenant_id=effective_tenant,
            profile_id=None,
            allowed=False,
            reason="missing_store_profile",
            registry_enabled=True,
        )

    allowed_profiles = {_clean_profile(v) for v in (cfg.get("allowed_profiles") or [])}
    allowed_profiles.discard(None)
    if allowed_profiles and profile not in allowed_profiles:
        return StoreProfileResolution(
            tenant_id=effective_tenant,
            profile_id=profile,
            allowed=False,
            reason="profile_not_allowed_for_tenant",
            registry_enabled=True,
        )
    return StoreProfileResolution(
        tenant_id=effective_tenant,
        profile_id=profile,
        allowed=True,
        registry_enabled=True,
    )
