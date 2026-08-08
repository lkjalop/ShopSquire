"""Data-driven governance for official workload-source enrollment."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "official_workload_sources.json"
_CLAIM_TYPES = {
    "concept_identity", "minimum_requirements", "recommended_requirements",
    "target_requirements", "compatibility", "certification",
    "workload_scope", "security_topology", "integration_capability",
    "software_feature", "hardware_floor", "capacity_sizing",
    "behavioral_performance", "benchmark_result", "exact_product_fit",
    "price", "availability",
}
_PARSER_TYPES = {"html", "pdf", "html_pdf", "structured_table"}
_RESOLUTION_OWNERS = {
    "catalog", "research", "buyer", "computation", "supplier",
    "tenant_policy", "human",
}


def load_official_source_manifest(path: Path | None = None) -> dict[str, Any]:
    source_path = path or DEFAULT_PATH
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {"schema_version": "official-workload-sources-v2", "sources": [], "errors": ["manifest_unreadable"]}
    if not isinstance(raw, Mapping):
        return {"schema_version": "official-workload-sources-v2", "sources": [], "errors": ["manifest_not_object"]}
    valid: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(list(raw.get("sources") or [])[:64]):
        if not isinstance(item, Mapping):
            errors.append(f"source_{index}:not_object")
            continue
        source_id = str(item.get("source_id") or "").strip()
        publisher = str(item.get("publisher") or "").strip()
        domains = [str(value).strip().lower().rstrip(".") for value in item.get("allowed_domains") or [] if str(value).strip()]
        entrypoints = [str(value).strip() for value in item.get("canonical_entrypoints") or [] if str(value).strip()]
        claims = [str(value).strip() for value in item.get("allowed_claim_types") or [] if str(value).strip()]
        forbidden_claims = [
            str(value).strip()
            for value in item.get("forbidden_claim_types") or []
            if str(value).strip()
        ]
        applicability = item.get("applicability")
        publisher_policy = item.get("publisher_policy")
        cache_policy = item.get("cache_policy")
        tenant_allowlist = item.get("tenant_allowlist")
        parser_type = str(item.get("parser_type") or "").strip()
        try:
            freshness = int(item.get("freshness_sla_hours") or 0)
        except (TypeError, ValueError):
            freshness = 0
        reasons: list[str] = []
        if not source_id or source_id in seen:
            reasons.append("source_id_missing_or_duplicate")
        if not publisher:
            reasons.append("publisher_missing")
        if not domains or any("*" in domain or "/" in domain for domain in domains):
            reasons.append("domain_allowlist_invalid")
        if not entrypoints:
            reasons.append("canonical_entrypoint_missing")
        elif any(
            urlparse(url).scheme != "https"
            or str(urlparse(url).hostname or "").lower().rstrip(".") not in domains
            for url in entrypoints
        ):
            reasons.append("canonical_entrypoint_outside_allowlist")
        if not claims or any(claim not in _CLAIM_TYPES for claim in claims):
            reasons.append("claim_policy_invalid")
        if (
            not forbidden_claims
            or any(claim not in _CLAIM_TYPES for claim in forbidden_claims)
            or set(claims) & set(forbidden_claims)
        ):
            reasons.append("forbidden_claim_policy_invalid")
        if (
            not isinstance(applicability, Mapping)
            or not list(applicability.get("workloads") or [])
            or not str(applicability.get("scope") or "").strip()
            or str(applicability.get("resolution_owner") or "").strip() not in _RESOLUTION_OWNERS
        ):
            reasons.append("applicability_invalid")
        if (
            not isinstance(publisher_policy, Mapping)
            or publisher_policy.get("direct_origin_required") is not True
            or not str(publisher_policy.get("policy_ref") or "").strip()
        ):
            reasons.append("publisher_policy_invalid")
        try:
            cache_max_age = int((cache_policy or {}).get("max_age_hours") or 0)
        except (AttributeError, TypeError, ValueError):
            cache_max_age = 0
        if (
            not isinstance(cache_policy, Mapping)
            or not isinstance(cache_policy.get("permitted"), bool)
            or not 1 <= cache_max_age <= 8760
        ):
            reasons.append("cache_policy_invalid")
        if (
            not isinstance(tenant_allowlist, Mapping)
            or str(tenant_allowlist.get("default") or "").strip() != "deny"
            or not str(tenant_allowlist.get("ref") or "").strip()
        ):
            reasons.append("tenant_allowlist_invalid")
        if parser_type not in _PARSER_TYPES:
            reasons.append("parser_type_invalid")
        if not 1 <= freshness <= 8760:
            reasons.append("freshness_sla_invalid")
        if reasons:
            errors.extend(f"{source_id or index}:{reason}" for reason in reasons)
            continue
        seen.add(source_id)
        valid.append({
            **dict(item),
            "source_id": source_id,
            "publisher": publisher,
            "allowed_domains": domains,
            "canonical_entrypoints": entrypoints,
            "allowed_claim_types": claims,
            "forbidden_claim_types": forbidden_claims,
            "parser_type": parser_type,
            "freshness_sla_hours": freshness,
        })
    return {**dict(raw), "sources": valid, "errors": errors}


def source_governance_readiness(path: Path | None = None) -> dict[str, Any]:
    manifest = load_official_source_manifest(path)
    sources = list(manifest.get("sources") or [])
    reviewed = [item for item in sources if item.get("review_status") == "approved"]
    pending = [
        item for item in sources
        if item.get("review_status") == "pending_independent_human_review"
    ]
    domains = sorted({domain for item in sources for domain in item.get("allowed_domains") or []})
    entrypoints = sorted({url for item in sources for url in item.get("canonical_entrypoints") or []})
    return {
        "schema_version": manifest.get("schema_version"),
        "valid_source_count": len(sources),
        "approved_source_count": len(reviewed),
        "pending_independent_human_review_count": len(pending),
        "domain_allowlist": domains,
        "canonical_entrypoints": entrypoints,
        "errors": list(manifest.get("errors") or []),
        "governance_status": manifest.get("governance_status") or "unknown",
        "operationally_enrolled": bool(sources and len(reviewed) == len(sources) and not manifest.get("errors")),
    }


def governed_sources_for_workload(
    workload: str,
    *,
    path: Path | None = None,
    include_pending_review: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Return explicitly applicable sources; never infer authority from a domain alone.

    Production execution excludes draft policies. Contract and fixture tests may opt in
    to pending policies while retaining their review status in every returned record.
    """
    normalized = str(workload or "").strip().lower()
    if not normalized:
        return ()
    manifest = load_official_source_manifest(path)
    matches: list[dict[str, Any]] = []
    for source in manifest.get("sources") or []:
        if source.get("review_status") != "approved" and not include_pending_review:
            continue
        workloads = {
            str(value).strip().lower()
            for value in (source.get("applicability") or {}).get("workloads") or []
        }
        if normalized in workloads:
            matches.append(dict(source))
    return tuple(matches)
