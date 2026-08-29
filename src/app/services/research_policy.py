"""Named policy profiles for governed public-source research."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.app.services.commerce_feature_readiness import (
    external_research_runtime_observation,
)


_DEFAULT_PATH = Path("config/research_policies.json")


def active_research_policy() -> dict[str, Any]:
    path = Path(os.getenv("RESEARCH_POLICY_PATH", str(_DEFAULT_PATH)))
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        registry = {"default_profile": "fail-closed", "profiles": {}}
    profile_id = str(
        os.getenv("RESEARCH_POLICY_PROFILE")
        or registry.get("default_profile")
        or "fail-closed"
    ).strip()
    profile = dict((registry.get("profiles") or {}).get(profile_id) or {})
    if not profile:
        return {
            "schema_version": "research-policy-v1", "profile_id": profile_id,
            "external_research_enabled": False, "auto_authorize_read_only": False,
            "pasted_url_policy": "receipt_only_zero_fetch", "max_provider_fanout": 0,
            "commerce_authority": "none", "status": "unknown_profile_fail_closed",
        }
    return {
        "schema_version": "research-policy-v1", "profile_id": profile_id,
        "external_research_enabled": bool(profile.get("external_research_enabled")),
        "auto_authorize_read_only": bool(profile.get("auto_authorize_read_only")),
        "pasted_url_policy": str(profile.get("pasted_url_policy") or "receipt_only_zero_fetch"),
        "max_provider_fanout": max(0, min(int(profile.get("max_provider_fanout") or 0), 3)),
        "commerce_authority": "none",
        "description": str(profile.get("description") or ""),
        "status": "active",
    }


def tenant_policy_auto_research_authorized() -> bool:
    policy = active_research_policy()
    if policy["external_research_enabled"] and policy["auto_authorize_read_only"]:
        return True
    # Backwards-compatible operator override used by existing proof scripts.
    return str(os.getenv("EXTERNAL_RESEARCH_AUTO_AUTHORIZED") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def external_research_runtime_status() -> dict[str, Any]:
    """Project the latest probe observation without performing network I/O."""

    status = str(os.getenv("EXTERNAL_RESEARCH_RUNTIME_STATUS") or "").strip().lower()
    reachable: bool | None = None
    if status in {"healthy", "reachable", "effective", "degraded"}:
        reachable = True
    elif status in {"unreachable", "failed"}:
        reachable = False
    observed = external_research_runtime_observation()
    configured = {
        "status": status or None,
        "reachable": reachable,
        "degraded": (status == "degraded") if status else None,
        "last_success_at": os.getenv("EXTERNAL_RESEARCH_LAST_SUCCESS_AT"),
        "last_failure_at": os.getenv("EXTERNAL_RESEARCH_LAST_FAILURE_AT"),
        "last_failure_code": os.getenv("EXTERNAL_RESEARCH_LAST_FAILURE_CODE"),
    }
    observed.update({key: value for key, value in configured.items() if value is not None})
    return observed


__all__ = [
    "active_research_policy",
    "external_research_runtime_status",
    "tenant_policy_auto_research_authorized",
]
