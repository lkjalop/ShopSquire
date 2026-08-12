"""Honest readiness for the two built-but-flag-gated commerce features (visual similarity +
external/internet search). CORE / vertical-blind.

Both features are inert by default: visual similarity needs a built FAISS index AND its flag;
external search needs an operator-configured search endpoint AND an allowlist AND its flag. These
helpers report whether a feature is ACTUALLY live (all preconditions met) or merely enabled-but-
inert — so we never claim a capability that won't produce results. Mirrors shipping_readiness().
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional


_RESEARCH_OBSERVATION_LOCK = threading.Lock()
_RESEARCH_RUNTIME_OBSERVATION: dict[str, Any] = {
    "reachable": None,
    "degraded": False,
    "last_discovery_success_at": None,
    "last_discovery_result_count": None,
    "last_official_fetch_success_at": None,
    "last_claim_compilation_success_at": None,
    "last_claim_compilation_count": None,
    "last_failure_at": None,
    "last_failure_code": None,
}


def reset_external_research_runtime_observation() -> None:
    """Reset process-local observations; intended for isolated tests/startup."""

    with _RESEARCH_OBSERVATION_LOCK:
        _RESEARCH_RUNTIME_OBSERVATION.update({
            "reachable": None,
            "degraded": False,
            "last_discovery_success_at": None,
            "last_discovery_result_count": None,
            "last_official_fetch_success_at": None,
            "last_claim_compilation_success_at": None,
            "last_claim_compilation_count": None,
            "last_failure_at": None,
            "last_failure_code": None,
        })


def external_research_runtime_observation() -> dict[str, Any]:
    with _RESEARCH_OBSERVATION_LOCK:
        return dict(_RESEARCH_RUNTIME_OBSERVATION)


def record_external_research_runtime_observation(
    research: Mapping[str, Any], *, observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Record executed discovery, origin and compilation outcomes truthfully.

    Discovery is successful only when the research service reports a completed
    discovery with at least one allowlisted result. An HTTP 200/empty result does
    not become effective discovery.
    """

    stamp = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    executions = [
        row for row in research.get("source_execution") or [] if isinstance(row, Mapping)
    ]
    discovery_successes = [
        row for row in executions
        if row.get("discovery_status") == "completed"
        and int(row.get("discovery_result_count") or 0) > 0
    ]
    discovery_receipts = [
        row for row in research.get("receipts") or []
        if isinstance(row, Mapping)
        and row.get("provider_capability") == "WEB_DISCOVERY"
    ]
    successful_discovery_receipts = [
        row for row in discovery_receipts
        if row.get("execution_status") == "completed"
        and row.get("network_execution") is True
        and int(row.get("result_count") or 0) > 0
    ]
    official_success = any(
        isinstance(receipt, Mapping)
        and receipt.get("provider_capability") == "OFFICIAL_ORIGIN_FETCH"
        and receipt.get("execution_status") == "completed"
        and receipt.get("network_execution") is True
        for receipt in research.get("receipts") or []
    )
    claim_count = len(list(research.get("claims") or []))
    claim_compiled_now = claim_count > 0 and any(
        str(row.get("origin_selection_mode") or "") not in {"", "evidence_cache", "unresolved"}
        for row in executions
    )
    failures = [
        str(row.get("reason") or "research_unresolved")
        for row in research.get("unresolved") or []
        if isinstance(row, Mapping)
    ]
    with _RESEARCH_OBSERVATION_LOCK:
        if discovery_successes or successful_discovery_receipts:
            _RESEARCH_RUNTIME_OBSERVATION.update({
                "reachable": True,
                "degraded": False,
                "last_discovery_success_at": stamp,
                "last_discovery_result_count": sum(
                    int(row.get("discovery_result_count") or 0)
                    for row in discovery_successes
                ) + sum(
                    int(row.get("result_count") or 0)
                    for row in successful_discovery_receipts
                ),
            })
        elif (
            any(row.get("discovery_status") == "failed" for row in executions)
            or any(row.get("execution_status") == "failed" for row in discovery_receipts)
        ):
            _RESEARCH_RUNTIME_OBSERVATION.update({
                "reachable": False,
                "degraded": True,
                "last_failure_at": stamp,
                "last_failure_code": "discovery_failed",
            })
        if official_success:
            _RESEARCH_RUNTIME_OBSERVATION["last_official_fetch_success_at"] = stamp
        if claim_compiled_now:
            _RESEARCH_RUNTIME_OBSERVATION.update({
                "last_claim_compilation_success_at": stamp,
                "last_claim_compilation_count": claim_count,
            })
        if failures:
            _RESEARCH_RUNTIME_OBSERVATION.update({
                "last_failure_at": stamp,
                "last_failure_code": failures[0][:160],
            })
        return dict(_RESEARCH_RUNTIME_OBSERVATION)


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
    tenant_id: str | None = None,
    probe_fn: Optional[Any] = None,
    runtime_status: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Report configured, reachable, effective and degraded as separate facts.

    No network work happens at import and no implicit probe is performed. Operators may
    inject a bounded ``probe_fn(endpoint)`` or a previously observed ``runtime_status``.
    A first local proof run may be explicitly enrolled; that permits the route to attempt
    its first call but does not manufacture a successful reachability observation.
    """
    enabled = _flag_on(flags, "EXTERNAL_RESEARCH_ENABLED", "EXTERNAL_RESEARCH_ENABLED")
    endpoint_url = str(os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or "").strip()
    endpoint = bool(endpoint_url)
    requirements_endpoint = bool(str(os.getenv("OFFICIAL_REQUIREMENTS_API_URL") or "").strip())
    requirements_domains = [
        value.strip().lower()
        for value in str(os.getenv("OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST") or "").split(",")
        if value.strip()
    ]
    allow = [a for a in (allowlist if allowlist is not None else (flags or {}).get("EXTERNAL_RESEARCH_ALLOWLIST") or []) if str(a or "").strip()]
    has_allowlist = len(allow) > 0
    tenant_allowlist = [
        value.strip()
        for value in str(os.getenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST") or "").split(",")
        if value.strip()
    ]
    tenant_enrollment = bool(tenant_allowlist) and (
        tenant_id is None or str(tenant_id).strip() in tenant_allowlist
    )
    source_policy_reviewed = bool(
        str(os.getenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY") or "").strip()
    )
    requirements_credential = bool(
        str(os.getenv("OFFICIAL_REQUIREMENTS_API_KEY") or "").strip()
    )
    publisher_policy = bool(
        str(os.getenv("OFFICIAL_REQUIREMENTS_PUBLISHER_POLICY_ID") or "").strip()
    )
    try:
        freshness_sla_hours = int(
            os.getenv("OFFICIAL_REQUIREMENTS_FRESHNESS_SLA_HOURS", "0") or 0
        )
    except (TypeError, ValueError):
        freshness_sla_hours = 0
    local_proof_enrolled = str(
        os.getenv("EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED") or "0"
    ).strip().lower() in {"1", "true", "yes", "on"}
    observed: dict[str, Any] = dict(runtime_status or {})
    probe_attempted = False
    if probe_fn is not None and endpoint:
        probe_attempted = True
        try:
            raw = probe_fn(endpoint_url)
            observed = dict(raw) if isinstance(raw, Mapping) else {"reachable": bool(raw)}
        except Exception as exc:
            observed = {
                "reachable": False,
                "error_code": "discovery_endpoint_unreachable",
                "error_type": type(exc).__name__,
            }
    raw_reachable = observed.get("reachable")
    reachable: bool | None = raw_reachable if isinstance(raw_reachable, bool) else None
    observed_state = str(observed.get("status") or "").strip().lower()
    if reachable is None and observed_state in {"healthy", "reachable", "effective"}:
        reachable = True
    elif reachable is None and observed_state in {"unreachable", "failed"}:
        reachable = False
    degraded = bool(observed.get("degraded")) or observed_state == "degraded"
    configured = endpoint
    policy_ready = bool(has_allowlist and tenant_enrollment)
    reachability_allows_attempt = reachable is True or (
        reachable is None and local_proof_enrolled
    )
    advisory_live = bool(
        enabled and configured and policy_ready and reachability_allows_attempt and not degraded
    )
    requirement_authority_ready = bool(
        advisory_live and requirements_endpoint and bool(requirements_domains)
        and tenant_enrollment and source_policy_reviewed and requirements_credential
        and publisher_policy and freshness_sla_hours > 0
    )
    live = bool(advisory_live or requirement_authority_ready)
    if not enabled:
        error_code = "external_research_disabled"
        reason = "EXTERNAL_RESEARCH_ENABLED is off"
    elif not endpoint:
        error_code = "discovery_endpoint_not_configured"
        reason = "EXTERNAL_RESEARCH_SEARCH_URL is not configured"
    elif not has_allowlist:
        error_code = "discovery_domain_allowlist_not_configured"
        reason = "no domain allowlist — results would be dropped by the allowlist guard"
    elif not tenant_enrollment:
        error_code = "external_research_tenant_not_enrolled"
        reason = "this tenant is not enrolled for external research"
    elif reachable is False:
        error_code = "discovery_endpoint_unreachable"
        reason = "the configured discovery endpoint was observed as unreachable"
    elif degraded:
        error_code = "discovery_endpoint_degraded"
        reason = "the configured discovery endpoint is degraded"
    elif reachable is None and not local_proof_enrolled:
        error_code = "discovery_reachability_not_observed"
        reason = "discovery is configured but reachability has not been observed"
    elif requirements_endpoint and not requirement_authority_ready:
        error_code = None
        reason = "live_advisory_only"
    else:
        error_code = None
        reason = "live"
    authority_reason = (
        "ready"
        if requirement_authority_ready
        else (
            "credential, publisher policy, independent source-policy review, tenant/domain "
            "allowlists, and a positive freshness SLA are required before claims can authorize requirements"
        )
    )
    try:
        from src.app.services.official_source_governance import source_governance_readiness
        governance = source_governance_readiness()
    except Exception:
        governance = {"operationally_enrolled": False, "valid_source_count": 0, "approved_source_count": 0}
    return {
        "feature": "external_search",
        "enabled": enabled,
        "live": live,
        "configured": configured,
        "policy_ready": policy_ready,
        "reachable": reachable,
        "effective": advisory_live,
        "degraded": degraded,
        "capability_status": (
            "disabled" if not enabled
            else "not_configured" if not endpoint
            else "domain_allowlist_missing" if not has_allowlist
            else "tenant_not_enrolled" if not tenant_enrollment
            else "unreachable" if reachable is False
            else "degraded" if degraded
            else "effective" if advisory_live and reachable is True
            else "local_proof_enrolled_unverified" if advisory_live
            else "configured_unverified"
        ),
        "error_code": error_code,
        "advisory_live": advisory_live,
        "requirement_authority_ready": requirement_authority_ready,
        "endpoint_configured": endpoint,
        "requirements_endpoint_configured": requirements_endpoint,
        "requirements_domain_allowlist_size": len(requirements_domains),
        "allowlist_size": len(allow),
        "tenant_enrollment_count": len(tenant_allowlist),
        "tenant_enrolled": tenant_enrollment,
        "local_proof_enrolled": local_proof_enrolled,
        "probe_attempted": probe_attempted,
        "last_success_at": (
            observed.get("last_success_at") or observed.get("last_discovery_success_at")
        ),
        "last_discovery_success_at": observed.get("last_discovery_success_at"),
        "last_discovery_result_count": observed.get("last_discovery_result_count"),
        "last_official_fetch_success_at": observed.get("last_official_fetch_success_at"),
        "last_claim_compilation_success_at": observed.get(
            "last_claim_compilation_success_at"
        ),
        "last_claim_compilation_count": observed.get("last_claim_compilation_count"),
        "last_failure_at": observed.get("last_failure_at"),
        "last_failure_code": observed.get("last_failure_code") or observed.get("error_code"),
        "source_policy_reviewed": source_policy_reviewed,
        "requirements_credential_configured": requirements_credential,
        "publisher_policy_configured": publisher_policy,
        "freshness_sla_hours": freshness_sla_hours,
        "reason": reason,
        "authority_reason": authority_reason,
        "source_governance": governance,
    }


def commerce_feature_readiness(
    flags: Optional[Dict[str, Any]] = None,
    *,
    allowlist: Optional[List[str]] = None,
    status_fn: Optional[Any] = None,
    external_probe_fn: Optional[Any] = None,
    external_runtime_status: Mapping[str, Any] | None = None,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """Combined readiness for both flag-gated commerce features — one honest snapshot."""
    return {
        "visual_similarity": visual_search_readiness(flags, status_fn=status_fn),
        "external_search": external_search_readiness(
            flags,
            allowlist=allowlist,
            tenant_id=tenant_id,
            probe_fn=external_probe_fn,
            runtime_status=(
                external_runtime_status
                if external_runtime_status is not None
                else external_research_runtime_observation()
            ),
        ),
    }
