"""Honest readiness for the two built-but-flag-gated commerce features (visual similarity +
external/internet search). CORE / vertical-blind.

Both features are inert by default: visual similarity needs a built FAISS index AND its flag;
external search needs an operator-configured search endpoint AND an allowlist AND its flag. These
helpers report whether a feature is ACTUALLY live (all preconditions met) or merely enabled-but-
inert — so we never claim a capability that won't produce results. Mirrors shipping_readiness().
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def _flag_on(flags: Optional[Dict[str, Any]], env_name: str, flag_name: str) -> bool:
    env = os.getenv(env_name)
    if env is not None:
        return str(env).strip().lower() in ("1", "true", "yes", "on")
    return bool((flags or {}).get(flag_name, False))


def visual_search_readiness(
    flags: Optional[Dict[str, Any]] = None,
    *,
    status_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """Is visual similarity LIVE? Requires IMAGE_SIMILARITY_ENABLED AND a ready FAISS index (CLIP +
    faiss installed + an index built). status_fn defaults to visual_search.status (injected for tests)."""
    enabled = _flag_on(flags, "IMAGE_SIMILARITY_ENABLED", "IMAGE_SIMILARITY_ENABLED")
    st: Dict[str, Any] = {}
    try:
        if status_fn is None:
            from src.app.services.visual_search import status as status_fn
        st = status_fn() or {}
    except Exception:
        st = {}
    index_ready = bool(st.get("index_ready"))
    deps_available = bool(st.get("available"))
    live = bool(enabled and index_ready)
    if not enabled:
        reason = "IMAGE_SIMILARITY_ENABLED is off"
    elif not deps_available:
        reason = "CLIP/FAISS not installed — run scripts/build_demo_visual_index.py on a host with deps"
    elif not index_ready:
        reason = "no FAISS index built — run scripts/build_demo_visual_index.py"
    else:
        reason = "live"
    return {
        "feature": "visual_similarity",
        "enabled": enabled,
        "live": live,
        "index_ready": index_ready,
        "deps_available": deps_available,
        "index_size": int(st.get("index_size") or 0),
        "reason": reason,
    }


def external_search_readiness(
    flags: Optional[Dict[str, Any]] = None,
    *,
    allowlist: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Is safe external/internet search LIVE? Requires EXTERNAL_RESEARCH_ENABLED AND a configured
    search endpoint (EXTERNAL_RESEARCH_SEARCH_URL) AND a non-empty domain allowlist."""
    enabled = _flag_on(flags, "EXTERNAL_RESEARCH_ENABLED", "EXTERNAL_RESEARCH_ENABLED")
    endpoint = bool(str(os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or "").strip())
    allow = [a for a in (allowlist if allowlist is not None else (flags or {}).get("EXTERNAL_RESEARCH_ALLOWLIST") or []) if str(a or "").strip()]
    has_allowlist = len(allow) > 0
    tenant_allowlist = [
        value.strip()
        for value in str(os.getenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST") or "").split(",")
        if value.strip()
    ]
    tenant_enrollment = bool(tenant_allowlist)
    source_policy_reviewed = bool(
        str(os.getenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY") or "").strip()
    )
    advisory_live = bool(enabled and endpoint and has_allowlist and tenant_enrollment)
    requirement_authority_ready = bool(advisory_live and source_policy_reviewed)
    live = advisory_live
    if not enabled:
        reason = "EXTERNAL_RESEARCH_ENABLED is off"
    elif not endpoint:
        reason = "EXTERNAL_RESEARCH_SEARCH_URL not configured — without it the NullFetcher returns nothing"
    elif not has_allowlist:
        reason = "no domain allowlist — results would be dropped by the allowlist guard"
    elif not tenant_enrollment:
        reason = "no tenant enrollment; the provider registry remains empty"
    elif not source_policy_reviewed:
        reason = "live_advisory_only"
    else:
        reason = "live"
    authority_reason = (
        "ready"
        if requirement_authority_ready
        else "independent source-policy review is required before claims can authorize requirements"
    )
    return {
        "feature": "external_search",
        "enabled": enabled,
        "live": live,
        "advisory_live": advisory_live,
        "requirement_authority_ready": requirement_authority_ready,
        "endpoint_configured": endpoint,
        "allowlist_size": len(allow),
        "tenant_enrollment_count": len(tenant_allowlist),
        "source_policy_reviewed": source_policy_reviewed,
        "reason": reason,
        "authority_reason": authority_reason,
    }


def commerce_feature_readiness(
    flags: Optional[Dict[str, Any]] = None,
    *,
    allowlist: Optional[List[str]] = None,
    status_fn: Optional[Any] = None,
) -> Dict[str, Any]:
    """Combined readiness for both flag-gated commerce features — one honest snapshot."""
    return {
        "visual_similarity": visual_search_readiness(flags, status_fn=status_fn),
        "external_search": external_search_readiness(flags, allowlist=allowlist),
    }
