"""Governed discovery, official-origin parsing and typed claim compilation.

The service is intentionally workload-light.  Source applicability comes from the
reviewed registry; parsers are source-specific because publisher documents are
contracts, not interchangeable prose.  Discovery snippets are never parsed.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import urlparse

from src.app.adapters.external_research_httpx import (
    AsyncHttpxResearchFetcher,
    HttpxResearchFetcher,
)
from src.app.adapters.official_origin_httpx import (
    AsyncGovernedOfficialOriginFetcher,
    GovernedOfficialOriginFetcher,
)
from src.app.services.official_evidence_cache import (
    DEFAULT_OFFICIAL_EVIDENCE_CACHE,
    OfficialEvidenceCache,
    OfficialEvidenceCacheEntry,
    OfficialEvidenceCacheKey,
)
from src.app.services.official_source_governance import governed_sources_for_workload
from src.app.services.cancellable_await import await_with_polling_cancel
from src.app.services.publisher_origin_verification import verify_publisher_origin
from src.app.services.research_certification_faults import active_research_fault
from src.app.services.recommendation_core.research_contracts import ProviderExecutionReceipt
from src.app.services.bounded_parser_execution import ParserBudget, execute_parser_bounded


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(str(data).split())
        if value:
            self.parts.append(value)


def _html_text(content: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(content.decode("utf-8", errors="ignore"))
    return " ".join(parser.parts)


def _claim(
    source_id: str, attribute: str, operator: str, value: Any,
    *, claim_type: str = "minimum_requirements", unit: str | None = None,
    requirement_class: str = "minimum",
    condition: str | None = None,
    statement: str, observed_at: str, citation_url: str,
) -> dict[str, Any]:
    digest = hashlib.sha256(
        f"{source_id}|{attribute}|{operator}|{value}|{citation_url}".encode()
    ).hexdigest()[:16]
    row = {
        "claim_id": f"official-{digest}",
        "attribute": attribute,
        "operator": operator,
        "value": value,
        "unit": unit,
        "requirement_class": requirement_class,
        "claim_type": claim_type,
        "claim_class": "attested",
        "authority_status": "verified_official",
        "freshness_status": "fresh",
        "source_id": source_id,
        "citation_url": citation_url,
        "observed_at": observed_at,
        "statement": statement,
        "acceptance_status": "accepted_official",
    }
    if condition:
        row["condition"] = condition
    return row


def _factory_io_claims(
    source_id: str, folded: str, observed_at: str, citation_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    product_claims: list[dict[str, Any]] = []
    if "windows 7 sp1+ or higher" in folded:
        product_claims.append(_claim(
            source_id, "operating_system", "one_of",
            ["Windows 11 Pro", "Windows 11 Enterprise", "Windows 10 Pro", "Windows 10 Enterprise", "Windows 7 SP1"],
            statement="Factory I/O documents Windows 7 SP1 or higher.",
            observed_at=observed_at, citation_url=citation_url,
        ))
    if "cpu with sse2 instruction set support" in folded:
        product_claims.append(_claim(
            source_id, "cpu_instruction_set", "equals", "SSE2",
            statement="Factory I/O requires a CPU with SSE2 support.",
            observed_at=observed_at, citation_url=citation_url,
        ))
    if "dx10, dx11, dx12 capable" in folded:
        product_claims.append(_claim(
            source_id, "graphics_api", "one_of", ["DX10", "DX11", "DX12"],
            claim_type="compatibility",
            statement="Factory I/O documents DX10, DX11 or DX12 capability.",
            observed_at=observed_at, citation_url=citation_url,
        ))
    return product_claims, []


def _hyperv_claims(
    source_id: str, folded: str, observed_at: str, citation_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    if "at least 4 gb of ram" in folded:
        rows.append(_claim(
            source_id, "ram_gb", ">=", 4, unit="GB",
            statement="Microsoft documents at least 4 GB for the host and notes that simultaneous VMs need additional memory.",
            observed_at=observed_at, citation_url=citation_url,
        ))
    if "windows 11 professional or enterprise" in folded:
        rows.append(_claim(
            source_id, "operating_system", "one_of", ["Windows 11 Pro", "Windows 11 Enterprise"],
            claim_type="compatibility",
            statement="Microsoft documents Windows 11 Professional or Enterprise for client Hyper-V.",
            observed_at=observed_at, citation_url=citation_url,
        ))
    for token, attribute, statement in (
        ("second-level address translation", "virtualization_slat", "Hyper-V requires second-level address translation."),
        ("vm monitor mode extensions", "virtualization_extensions", "Hyper-V requires VM Monitor Mode extensions."),
        ("data execution prevention", "hardware_dep", "Hyper-V requires hardware-enforced data execution prevention."),
    ):
        if token in folded:
            rows.append(_claim(
                source_id, attribute, "equals", True, claim_type="compatibility",
                statement=statement, observed_at=observed_at, citation_url=citation_url,
            ))
    return rows, []


def _context_claims(
    source_id: str, folded: str, observed_at: str, citation_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    marker = "ics" if source_id == "mitre_attack_ics" else "digital twin"
    if marker not in folded:
        return [], []
    return [], [{
        "claim_id": f"context-{source_id}", "source_id": source_id,
        "claim_type": "workload_scope", "status": "corroborated",
        "statement": "Official material corroborates the workload scope; it does not establish a hardware floor.",
        "citation_url": citation_url, "observed_at": observed_at,
        "authority_status": "verified_official", "freshness_status": "fresh",
    }]


def _workstation_application_claims(
    source_id: str, folded: str, observed_at: str, citation_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Conservative parser for reviewed Blender/Autodesk/Epic requirement pages."""

    rows: list[dict[str, Any]] = []
    if source_id == "blender_official_requirements":
        if "32 gb ram" in folded:
            rows.append(_claim(
                source_id, "ram_gb", ">=", 32, unit="GB",
                claim_type="recommended_requirements", requirement_class="recommended",
                statement="Blender publishes 32 GB RAM in its recommended tier.",
                observed_at=observed_at, citation_url=citation_url,
            ))
        if "8 gb vram" in folded:
            rows.append(_claim(
                source_id, "gpu_vram_gb", ">=", 8, unit="GB",
                claim_type="recommended_requirements", requirement_class="recommended",
                statement="Blender publishes 8 GB VRAM in its recommended tier.",
                observed_at=observed_at, citation_url=citation_url,
            ))
    elif source_id in {"autodesk_autocad_requirements", "autodesk_revit_requirements"}:
        if "32 gb" in folded and ("ram" in folded or "memory" in folded):
            rows.append(_claim(
                source_id, "ram_gb", ">=", 32, unit="GB",
                claim_type="recommended_requirements", requirement_class="recommended",
                condition=(
                    "large datasets, point clouds, or 3D modelling"
                    if source_id == "autodesk_autocad_requirements"
                    else "large, complex Revit models"
                ),
                statement="The Autodesk requirement page publishes a 32 GB memory tier.",
                observed_at=observed_at, citation_url=citation_url,
            ))
        if source_id == "autodesk_autocad_requirements" and "directx 12" in folded:
            rows.append(_claim(
                source_id, "graphics_api", "equals", "DX12", claim_type="compatibility",
                statement="The AutoCAD requirement page documents DirectX 12 capability.",
                observed_at=observed_at, citation_url=citation_url,
            ))
        if (
            source_id == "autodesk_autocad_requirements"
            and "point clouds" in folded
            and ("12 gb vram or greater" in folded or "12gb vram or greater" in folded)
        ):
            rows.extend([
                _claim(
                    source_id, "gpu_vram_gb", ">=", 12, unit="GB",
                    claim_type="target_requirements", requirement_class="target",
                    condition="large datasets, point clouds, or 3D modelling",
                    statement="AutoCAD publishes 12 GB VRAM or greater for large datasets, point clouds, and 3D modelling.",
                    observed_at=observed_at, citation_url=citation_url,
                ),
                _claim(
                    source_id, "gpu_class", "equals", "workstation",
                    claim_type="target_requirements", requirement_class="target",
                    condition="large datasets, point clouds, or 3D modelling",
                    statement="AutoCAD specifies a workstation-class graphics card for the large-dataset and point-cloud tier.",
                    observed_at=observed_at, citation_url=citation_url,
                ),
            ])
    elif source_id == "epic_unreal_engine_requirements":
        if "32 gb ram" in folded:
            rows.append(_claim(
                source_id, "ram_gb", ">=", 32, unit="GB",
                claim_type="recommended_requirements", requirement_class="recommended",
                statement="Epic publishes 32 GB RAM in the recommended hardware tier.",
                observed_at=observed_at, citation_url=citation_url,
            ))
        if "8 gb or more" in folded and "graphics ram" in folded:
            rows.append(_claim(
                source_id, "gpu_vram_gb", ">=", 8, unit="GB",
                claim_type="recommended_requirements", requirement_class="recommended",
                statement="Epic publishes 8 GB or more graphics RAM in the recommended tier.",
                observed_at=observed_at, citation_url=citation_url,
            ))
        if "directx 12" in folded:
            rows.append(_claim(
                source_id, "graphics_api", "equals", "DX12", claim_type="compatibility",
                statement="Epic documents DirectX 12 for supported Unreal Engine feature paths.",
                observed_at=observed_at, citation_url=citation_url,
            ))
    return rows, []


_SOURCE_PARSERS = {
    "factory_io_official_docs": _factory_io_claims,
    "microsoft_learn_hyperv": _hyperv_claims,
    "nist_digital_twin_cybersecurity": _context_claims,
    "nist_manufacturing_digital_twins": _context_claims,
    "mitre_attack_ics": _context_claims,
    "blender_official_requirements": _workstation_application_claims,
    "autodesk_autocad_requirements": _workstation_application_claims,
    "autodesk_revit_requirements": _workstation_application_claims,
    "epic_unreal_engine_requirements": _workstation_application_claims,
}

_PARSER_VERSION = "official-source-parser-v2"
_HTML_CONTENT_TYPES = {"text/html", "text/plain", "application/xhtml+xml"}


def compile_source_claims(
    source_id: str, content: bytes, *, observed_at: str, citation_url: str,
    allow_generic: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile claims through a source parser or the conservative generic fallback."""

    parser = _SOURCE_PARSERS.get(source_id)
    source_text = _html_text(content)
    if parser is not None:
        return parser(source_id, source_text.casefold(), observed_at, citation_url)
    if not allow_generic:
        return [], []

    # Provider-neutral extraction is a bounded fallback for reviewed publishers
    # without a dedicated parser.  Search snippets never enter this function;
    # the caller has already completed an allowlisted official-origin fetch.
    from src.app.services.generic_requirement_extractor import (
        critique_extracted_requirements,
        extract_generic_requirements,
    )

    observed = _parse_time(observed_at)
    if observed is None:
        return [], []
    candidates = extract_generic_requirements(
        source_text, citation_url=citation_url, observed_at=observed,
    )
    critique = critique_extracted_requirements(
        candidates, source_text=source_text, accepted_url=citation_url,
    )
    rows: list[dict[str, Any]] = []
    for candidate in critique.accepted:
        claim_type = {
            "minimum": "minimum_requirements",
            "recommended": "recommended_requirements",
            "target": "target_requirements",
            "conditional": "recommended_requirements",
        }[candidate.requirement_class]
        row = _claim(
            source_id, candidate.attribute, candidate.operator, candidate.value,
            unit=candidate.unit, claim_type=claim_type,
            requirement_class=candidate.requirement_class,
            condition=candidate.condition,
            statement=candidate.quoted_evidence_span,
            observed_at=observed_at, citation_url=citation_url,
        )
        row["page_section"] = candidate.page_section
        row["quoted_evidence_span"] = candidate.quoted_evidence_span
        row["extractor"] = "provider_neutral_deterministic"
        rows.append(row)
    return rows, []


def _receipt(raw: dict[str, Any], *, run_id: str, capability: str, index: int) -> dict[str, Any]:
    certified = all(raw.get(key) is not None for key in (
        "provider_endpoint_host", "query_hash", "http_status", "response_body_hash",
    )) and bool(raw.get("network_execution"))
    model = ProviderExecutionReceipt(
        receipt_id=f"{run_id}:{index}", execution_id=f"{run_id}:{index}",
        provider_capability=capability,
        provider_id=str(raw.get("provider_id") or "governed_official_research"),
        certification_run_id=run_id if certified else None,
        provider_endpoint_host=raw.get("provider_endpoint_host"),
        query_id=raw.get("query_id"), query_hash=raw.get("query_hash"),
        query_purpose=raw.get("query_purpose"),
        obligation_ids=["official-requirements"],
        execution_status=raw.get("execution_status", "failed"),
        fixture=bool(raw.get("fixture")),
        network_execution=bool(raw.get("network_execution")),
        external_call_dispatched=bool(raw.get("external_call_dispatched")),
        cache_status=raw.get("cache_status", "miss"),
        billing_class=raw.get("billing_class", "unknown"),
        started_at=raw.get("started_at"), completed_at=raw.get("completed_at"),
        http_status=raw.get("http_status"), result_count=raw.get("result_count"),
        allowlisted_result_count=raw.get("allowlisted_result_count"),
        engines_queried=list(raw.get("engines_queried") or []),
        engines_responded=list(raw.get("engines_responded") or []),
        engine_failures=list(raw.get("engine_failures") or []),
        engine_reliability=list(raw.get("engine_reliability") or []),
        suppressed_engines=list(raw.get("suppressed_engines") or []),
        request_latency_ms=raw.get("request_latency_ms"),
        degradation_reasons=list(raw.get("degradation_reasons") or []),
        provider_status=raw.get("provider_status"),
        response_body_hash=raw.get("response_body_hash"),
        origin_content_type=raw.get("origin_content_type"),
        selected_origin_urls=list(raw.get("selected_origin_urls") or []),
        origin_observed_at=raw.get("observed_at"), rejection_reason=raw.get("error"),
    )
    return model.model_dump(mode="json")


def _source_query(source: dict[str, Any]) -> str:
    """Build a bounded discovery query from governed manifest data only."""

    publisher = str(source.get("publisher") or "official publisher")
    artefact = str((source.get("artefact_patterns") or [publisher])[0])
    claim_types = set(source.get("allowed_claim_types") or [])
    purpose = (
        "system requirements compatibility"
        if claim_types.intersection({"minimum_requirements", "recommended_requirements", "compatibility"})
        else "workload scope"
    )
    # Domain filtering is applied to structured results after retrieval. The
    # `site:` operator couples queries to engines that currently challenge or
    # silently return zero results, so it is deliberately not used here.
    return f"{artefact} {publisher} official {purpose}"[:240]


def _source_discovery_queries(source: dict[str, Any]) -> tuple[str, ...]:
    """Return a bounded, progressively broader official-origin query set.

    Queries are built exclusively from reviewed manifest data.  Raw buyer text is
    deliberately excluded so discovery cannot leak case-specific or personal
    information.  Callers stop as soon as an acceptable canonical-family origin is
    found, keeping the common path to one free local request.
    """

    publisher = str(source.get("publisher") or "official publisher").strip()
    artefacts = [
        str(value).strip()
        for value in source.get("artefact_patterns") or []
        if str(value).strip()
    ]
    primary = _source_query(source)
    candidates = [primary]
    if len(artefacts) > 1:
        candidates.append(f"{artefacts[1]} {publisher} official documentation"[:240])
    claim_types = set(source.get("allowed_claim_types") or [])
    if claim_types.intersection({"minimum_requirements", "recommended_requirements", "compatibility"}):
        candidates.append(f"{publisher} official system requirements compatibility"[:240])
    else:
        candidates.append(f"{publisher} official documentation workload scope"[:240])
    return tuple(dict.fromkeys(value for value in candidates if value))[:3]


def _source_discovery_query_plan(source: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Attach a material coverage axis to each bounded discovery query."""

    queries = _source_discovery_queries(source)
    claim_types = set(source.get("allowed_claim_types") or [])
    axes = (
        ("named_software", "local_execution", "hardware_compatibility")
        if claim_types.intersection({
            "minimum_requirements", "recommended_requirements", "compatibility",
        })
        else ("named_concept", "application_scope", "official_guidance")
    )
    return tuple((axes[index], query) for index, query in enumerate(queries))


def _domain_allowed(url: str, domains: list[str]) -> bool:
    host = str(urlparse(url).hostname or "").lower().rstrip(".")
    return bool(host) and any(
        host == domain or host.endswith("." + domain)
        for raw in domains
        if (domain := str(raw or "").strip().lower().rstrip("."))
    )


def _normalized_origin(value: str) -> tuple[str, str]:
    parsed = urlparse(str(value or ""))
    host = str(parsed.hostname or "").lower().rstrip(".")
    path = "/" + str(parsed.path or "/").strip("/")
    return host, path.rstrip("/") or "/"


def _discovered_origin_for_source(
    results: list[dict[str, Any]], source: dict[str, Any],
) -> tuple[str, str | None]:
    """Select only an applicable official page for an enrolled source.

    For sources with canonical entrypoints, an arbitrary page on the same
    hostname is insufficient. Prefer an exact canonical page, then a child of
    a canonical directory. Open-domain selection is reserved for a future
    vendor-resolution source that genuinely has no canonical entrypoint.
    """

    domains = list(source.get("allowed_domains") or [])
    candidates = [
        row for row in results
        if _domain_allowed(str(row.get("url") or ""), domains)
    ]
    canonicals = [
        str(value) for value in source.get("canonical_entrypoints") or [] if str(value).strip()
    ]
    if not canonicals:
        if not candidates:
            return "", "official_origin_not_discovered"
        ranked = sorted(candidates, key=lambda row: _origin_quality_score(row, source), reverse=True)
        return str(ranked[0].get("url") or ""), None
    canonical_keys = {_normalized_origin(value): value for value in canonicals}
    eligible: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_url = str(candidate.get("url") or "")
        if _normalized_origin(candidate_url) in canonical_keys:
            eligible.append(candidate)
            continue
        candidate_host, candidate_path = _normalized_origin(candidate_url)
        for canonical in canonicals:
            canonical_host, canonical_path = _normalized_origin(canonical)
            if candidate_host == canonical_host and (
                candidate_path.startswith(canonical_path.rstrip("/") + "/")
            ):
                eligible.append(candidate)
                break
    if eligible:
        ranked = sorted(eligible, key=lambda row: _origin_quality_score(row, source), reverse=True)
        return str(ranked[0].get("url") or ""), None
    return "", "discovered_origin_outside_canonical_family"


def _origin_quality_score(result: dict[str, Any], source: dict[str, Any]) -> int:
    """Deterministically prefer exact, requirements-bearing official pages."""

    url = str(result.get("url") or "")
    title = str(result.get("title") or "").lower()
    _host, path = _normalized_origin(url)
    text = f"{title} {path.lower()}"
    canonicals = [str(value) for value in source.get("canonical_entrypoints") or []]
    score = 0
    if any(_normalized_origin(url) == _normalized_origin(value) for value in canonicals):
        score += 1000
    if any(token in text for token in ("system requirement", "requirements", "compatibility")):
        score += 180
    if any(token in text for token in ("manual", "documentation", "docs")):
        score += 80
    artefact_tokens = {
        token.lower()
        for value in source.get("artefact_patterns") or []
        for token in str(value).split()
        if len(token) >= 4
    }
    score += min(120, 20 * sum(token in text for token in artefact_tokens))
    if any(token in text for token in ("forum", "community", "blog", "snippet")):
        score -= 160
    return score


def _policy_version(source: dict[str, Any]) -> str:
    return str((source.get("publisher_policy") or {}).get("policy_ref") or "unknown")[:160]


def _parser_version(source_id: str) -> str:
    return f"{_PARSER_VERSION}:{source_id}"


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_policy_errors(
    source: dict[str, Any], *, workload: str | None,
) -> list[str]:
    errors: list[str] = []
    if source.get("review_status") != "approved":
        errors.append("source_policy_not_approved")
    allowed = set(source.get("allowed_claim_types") or [])
    forbidden = set(source.get("forbidden_claim_types") or [])
    if not allowed or not forbidden or allowed & forbidden:
        errors.append("source_claim_policy_invalid")
    applicability = source.get("applicability") or {}
    workloads = {str(value).strip().lower() for value in applicability.get("workloads") or []}
    if not workloads or not str(applicability.get("scope") or "").strip():
        errors.append("source_applicability_missing")
    if workload and str(workload).strip().lower() not in workloads:
        errors.append("source_not_applicable_to_workload")
    if source.get("parser_type") not in {"html", "html_pdf", "pdf", "structured_table"}:
        errors.append("source_parser_type_invalid")
    if (source.get("publisher_policy") or {}).get("direct_origin_required") is not True:
        errors.append("direct_origin_policy_required")
    try:
        freshness = int(source.get("freshness_sla_hours") or 0)
    except (TypeError, ValueError):
        freshness = 0
    if not 1 <= freshness <= 8760:
        errors.append("source_freshness_sla_invalid")
    domains = list(source.get("allowed_domains") or [])
    canonical = list(source.get("canonical_entrypoints") or [])
    if not domains or any(not _domain_allowed(str(url), domains) for url in canonical):
        errors.append("canonical_domain_not_allowlisted")
    return errors


def _compiled_claims_allowed(
    source: dict[str, Any],
    product_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    *,
    observed_at: str,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    allowed = set(source.get("allowed_claim_types") or [])
    forbidden = set(source.get("forbidden_claim_types") or [])
    reasons: list[str] = []
    emitted = [*product_rows, *context_rows]
    invalid = {
        str(row.get("claim_type") or "")
        for row in emitted
        if row.get("claim_type") not in allowed or row.get("claim_type") in forbidden
    }
    if invalid:
        return [], [], [f"emitted_claim_type_not_allowed:{value}" for value in sorted(invalid)]
    observed = _parse_time(observed_at)
    freshness_sla = int(source.get("freshness_sla_hours") or 0)
    if observed is None:
        return [], [], ["origin_observed_at_invalid"]
    fresh = now <= observed + timedelta(hours=freshness_sla)
    freshness = "fresh" if fresh else "stale"
    for row in emitted:
        row["freshness_status"] = freshness
        row["source_applicability"] = dict(source.get("applicability") or {})
        row["parser_type"] = source.get("parser_type")
        row["policy_version"] = _policy_version(source)
    if not fresh:
        reasons.append("origin_evidence_stale")
        return [], [], reasons
    return product_rows, context_rows, reasons


def _evidence_ladder_projection(
    *, receipts: list[dict[str, Any]], source_execution: list[dict[str, Any]],
    evidence_outcome: str, search_configured: bool,
) -> list[dict[str, Any]]:
    discovery = [row for row in receipts if row["provider_capability"] == "WEB_DISCOVERY"]
    origins = [row for row in receipts if row["provider_capability"] == "OFFICIAL_ORIGIN_FETCH"]
    canonical_origins = [
        row for row in origins
        if row.get("query_purpose") in {
            "canonical_official_origin_fetch", "official_evidence_cache",
        }
    ]
    engine_failures = [
        failure for row in discovery for failure in row.get("engine_failures") or []
    ]
    degradation_reasons = sorted({
        reason for row in discovery for reason in row.get("degradation_reasons") or []
    })
    allowlisted_hits = sum(int(row.get("allowlisted_result_count") or 0) for row in discovery)
    discovery_status = (
        "degraded" if degradation_reasons
        else "completed" if discovery
        else "not_needed" if not any(
            row.get("discovery_status") in {"failed", "attempted_empty"}
            for row in source_execution
        )
        else "not_configured" if not search_configured
        else "failed"
    )
    return [
        {
            "tier": 0, "mechanism": "evidence_cache",
            "execution_status": "completed" if any(row["cache_status"] == "fresh_hit" for row in origins) else "miss",
            "rejection_reason": None if any(row["cache_status"] == "fresh_hit" for row in origins) else "cache_miss",
            "billing_class": "free",
        },
        {
            "tier": 1, "mechanism": "enrolled_canonical_origin",
            "execution_status": "completed" if any(
                row["execution_status"] == "completed" for row in canonical_origins
            ) else "failed" if canonical_origins else "not_attempted",
            "rejection_reason": (
                None if canonical_origins
                else "explicit_novel_discovery_requested" if discovery
                else "canonical_origin_not_attempted"
            ),
            "completed_count": sum(
                row["execution_status"] == "completed" for row in canonical_origins
            ),
            "attempted_count": len(canonical_origins), "billing_class": "free",
        },
        {
            "tier": 2, "mechanism": "buyer_upload_or_link",
            "execution_status": "not_attempted", "rejection_reason": "no_upload_provided",
            "billing_class": "free",
        },
        {
            "tier": 3, "mechanism": "vendor_resolution",
            "execution_status": "not_attempted",
            "rejection_reason": "named_vendor_resolution_not_requested",
            "billing_class": "free",
        },
        {
            "tier": 4, "mechanism": "self_hosted_discovery",
            "execution_status": discovery_status,
            "rejection_reason": degradation_reasons[0] if degradation_reasons else None,
            "engines_queried": sorted({
                engine for row in discovery for engine in row.get("engines_queried") or []
            }),
            "engines_responded": sorted({
                engine for row in discovery for engine in row.get("engines_responded") or []
            }),
            "engine_failures": engine_failures,
            "engine_reliability": [
                row
                for receipt in discovery
                for row in receipt.get("engine_reliability") or []
            ][-16:],
            "suppressed_engines": sorted({
                engine
                for row in discovery
                for engine in row.get("suppressed_engines") or []
            }),
            "allowlisted_result_count": allowlisted_hits,
            "dispatch_count": sum(bool(row.get("external_call_dispatched")) for row in discovery),
            "billing_class": "free",
        },
        {
            "tier": 5, "mechanism": "paid_discovery",
            "execution_status": "not_attempted", "rejection_reason": "provider_not_enrolled",
            "billing_class": "paid", "paid_calls": 0,
        },
        {
            "tier": 6, "mechanism": "governed_abstention",
            "execution_status": "activated" if evidence_outcome != "product_requirements" else "not_needed",
            "rejection_reason": (
                "material_evidence_unresolved" if evidence_outcome == "unresolved"
                else "product_requirements_not_established" if evidence_outcome == "context_only"
                else None
            ),
            "billing_class": "not_applicable",
        },
    ]


async def research_official_sources(
    purpose: str,
    *,
    search_url_template: str,
    sources: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    plan_id: str | None = None,
    hypothesis_ids: list[str] | None = None,
    tenant_id: str = "default",
    workload: str | None = None,
    novel_source_ids: set[str] | None = None,
    evidence_cache: OfficialEvidenceCache | None = None,
    now: datetime | None = None,
    total_timeout_s: float = 30.0,
    parser_max_input_bytes: int = 2 * 1024 * 1024,
    parser_timeout_s: float = 1.0,
    parser_max_claims: int = 128,
    cancellation_requested: Callable[[], bool] | None = None,
    _sync_transport_compat: bool = False,
) -> dict[str, Any]:
    """Fetch reviewed origins without blocking or outliving the request task."""

    run_id = f"research-{uuid.uuid4().hex[:12]}"
    started_monotonic = time.monotonic()
    deadline_monotonic = started_monotonic + max(0.0, float(total_timeout_s))
    cancelled = False
    parser_budget = ParserBudget(
        max_input_bytes=parser_max_input_bytes,
        timeout_ms=max(10, round(float(parser_timeout_s) * 1_000)),
        max_claims=parser_max_claims,
    ).normalized()

    def remaining_timeout(cap_s: float) -> float:
        return max(0.0, min(cap_s, deadline_monotonic - time.monotonic()))

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    # An unscoped caller may still fetch, but must not share evidence across buyers.
    # Route wiring should always pass the authenticated tenant before relying on cache.
    if evidence_cache is not None:
        cache = evidence_cache
    elif tenant_id == "default":
        cache = OfficialEvidenceCache(max_entries=1)
    else:
        cache = DEFAULT_OFFICIAL_EVIDENCE_CACHE
    novel = set(novel_source_ids or set())
    receipts: list[dict[str, Any]] = []
    source_execution: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    context_claims: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for source in sources[:4]:
        source_id = str(source["source_id"])
        domains = list(source["allowed_domains"])
        canonical = str((source.get("canonical_entrypoints") or [""])[0])
        execution = {
            "source_id": source_id,
            "publisher": source.get("publisher"),
            "parser_type": source.get("parser_type"),
            "parser_version": _parser_version(source_id),
            "policy_version": _policy_version(source),
            "freshness_sla_hours": source.get("freshness_sla_hours"),
            "origin_selection_mode": "unresolved",
            "canonical_url": canonical or None,
            "selected_origin_url": None,
            "cache_status": "miss",
            "canonical_fetch_status": "not_attempted",
            "discovery_status": "not_needed",
            "discovery_reason": None,
            "discovery_result_count": 0,
            "discovery_queries": list(_source_discovery_queries(source)),
            "deadline_status": "within_deadline",
            "parser_coverage": {
                "pages_fetched": 0,
                "candidate_claims": 0,
                "accepted_claims": 0,
                "rejected_claims": 0,
                "context_claims": 0,
                "parse_status": "not_attempted",
            },
            "parser_budget": {
                "status": "not_attempted",
                "input_bytes": 0,
                "max_input_bytes": parser_budget.max_input_bytes,
                "timeout_ms": parser_budget.timeout_ms,
                "max_claims": parser_budget.max_claims,
                "elapsed_ms": 0.0,
                "late_result_quarantined": False,
                "failure_code": None,
                "error_type": None,
            },
        }
        if cancellation_requested and cancellation_requested():
            cancelled = True
            execution["deadline_status"] = "cancelled_before_dispatch"
            unresolved.append({"source_id": source_id, "reason": "buyer_request_cancelled"})
            source_execution.append(execution)
            break
        if remaining_timeout(15.0) <= 0:
            execution["deadline_status"] = "exceeded_before_dispatch"
            unresolved.append({"source_id": source_id, "reason": "research_total_deadline_exceeded"})
            source_execution.append(execution)
            continue
        policy_errors = _source_policy_errors(source, workload=workload)
        if policy_errors:
            unresolved.extend({"source_id": source_id, "reason": reason} for reason in policy_errors)
            source_execution.append(execution)
            continue

        parser_version = _parser_version(source_id)
        policy_version = _policy_version(source)
        cached, cache_status = cache.get_latest(
            tenant_id=tenant_id, source_id=source_id, canonical_url=canonical or None,
            parser_version=parser_version, policy_version=policy_version, now=current,
        )
        execution["cache_status"] = cache_status
        if cached is not None and cache_status == "fresh_hit":
            stamp = current.isoformat()
            cache_raw = {
                "provider_id": "official_evidence_cache",
                "execution_status": "completed", "network_execution": False,
                "external_call_dispatched": False, "cache_status": "fresh_hit",
                "billing_class": "not_applicable", "started_at": stamp,
                "completed_at": stamp, "query_hash": cached.key.content_hash,
                "response_body_hash": cached.key.content_hash,
                "provider_endpoint_host": urlparse(canonical).hostname,
                "selected_origin_urls": [canonical], "origin_content_type": cached.content_type,
                "observed_at": cached.observed_at.isoformat(), "query_id": source_id,
                "query_purpose": "official_evidence_cache",
            }
            receipts.append(_receipt(
                cache_raw, run_id=run_id, capability="OFFICIAL_ORIGIN_FETCH",
                index=len(receipts) + 1,
            ))
            claims.extend(dict(row) for row in cached.claims)
            context_claims.extend(dict(row) for row in cached.context_claims)
            execution.update({
                "origin_selection_mode": "evidence_cache",
                "selected_origin_url": cached.key.canonical_url,
                "parser_coverage": {
                    "pages_fetched": 0,
                    "candidate_claims": len(cached.claims) + len(cached.context_claims),
                    "accepted_claims": len(cached.claims),
                    "rejected_claims": 0,
                    "context_claims": len(cached.context_claims),
                    "parse_status": "cache_hit",
                },
                "parser_budget": {
                    **execution["parser_budget"],
                    "status": "not_needed_cache_hit",
                },
            })
            if (source.get("publisher_policy") or {}).get(
                "semantic_ownership_verification_required"
            ):
                execution["publisher_origin_verification"] = {
                    "status": "cached_prior_verification",
                    "ownership_authority": "not_independently_verified",
                }
            source_execution.append(execution)
            continue

        selected = canonical
        origin: dict[str, Any] | None = None
        explicit_novel = source_id in novel
        if canonical and not explicit_novel:
            if cancellation_requested and cancellation_requested():
                cancelled = True
                execution["deadline_status"] = "cancelled_before_canonical_fetch"
                unresolved.append({"source_id": source_id, "reason": "buyer_request_cancelled"})
                source_execution.append(execution)
                break
            fetch_timeout = remaining_timeout(15.0)
            if fetch_timeout <= 0:
                execution["deadline_status"] = "exceeded_before_canonical_fetch"
                unresolved.append({
                    "source_id": source_id, "reason": "research_total_deadline_exceeded",
                })
                source_execution.append(execution)
                continue
            if _sync_transport_compat:
                origin = GovernedOfficialOriginFetcher(max_bytes=8 * 1024 * 1024).fetch(
                    canonical, allowlist=domains, timeout_s=fetch_timeout,
                    certification_run_id=run_id,
                )
            else:
                origin, cancelled_during_fetch = await await_with_polling_cancel(
                    AsyncGovernedOfficialOriginFetcher(
                        max_bytes=8 * 1024 * 1024,
                    ).fetch_async(
                        canonical, allowlist=domains, timeout_s=fetch_timeout,
                        certification_run_id=run_id,
                    ),
                    cancellation_requested=cancellation_requested,
                )
                if cancelled_during_fetch:
                    cancelled = True
                    execution["deadline_status"] = "cancelled_during_canonical_fetch"
                    unresolved.append({
                        "source_id": source_id, "reason": "buyer_request_cancelled",
                    })
                    source_execution.append(execution)
                    break
            execution["canonical_fetch_status"] = origin["status"]
            raw_canonical_receipt = dict(origin["receipt"])
            raw_canonical_receipt.update({
                "billing_class": "free", "origin_content_type": origin.get("content_type"),
                "query_id": source_id, "query_purpose": "canonical_official_origin_fetch",
                "selected_origin_urls": [canonical],
            })
            receipts.append(_receipt(
                raw_canonical_receipt, run_id=run_id,
                capability="OFFICIAL_ORIGIN_FETCH", index=len(receipts) + 1,
            ))
            if origin["status"] == "completed":
                execution.update({
                    "origin_selection_mode": "canonical_direct",
                    "selected_origin_url": canonical,
                })
            if cancellation_requested and cancellation_requested():
                cancelled = True
                execution["deadline_status"] = "cancelled_after_canonical_fetch"
                unresolved.append({"source_id": source_id, "reason": "buyer_request_cancelled"})
                source_execution.append(execution)
                break

        needs_discovery = explicit_novel or not canonical or not origin or origin["status"] != "completed"
        if needs_discovery:
            reason = (
                "explicitly_novel" if explicit_novel
                else "canonical_missing" if not canonical
                else "canonical_fetch_failed"
            )
            execution["discovery_reason"] = reason
            if not search_url_template:
                execution["discovery_status"] = "failed"
                unresolved.append({"source_id": source_id, "reason": "discovery_not_configured"})
                source_execution.append(execution)
                continue
            discovery = (
                HttpxResearchFetcher(
                    search_url_template=search_url_template, allow_private=True,
                ) if _sync_transport_compat else AsyncHttpxResearchFetcher(
                    search_url_template=search_url_template, allow_private=True,
                )
            )
            discovery_timeout = remaining_timeout(12.0)
            if discovery_timeout <= 0:
                execution["deadline_status"] = "exceeded_before_discovery"
                execution["discovery_status"] = "not_attempted_deadline"
                unresolved.append({
                    "source_id": source_id, "reason": "research_total_deadline_exceeded",
                })
                source_execution.append(execution)
                continue
            results: list[dict[str, Any]] = []
            selected = ""
            selection_error: str | None = "official_origin_not_discovered"
            attempted = 0
            completed_attempt = False
            query_axes: list[str] = []
            for query_index, (query_axis, query) in enumerate(
                _source_discovery_query_plan(source), 1,
            ):
                if cancellation_requested and cancellation_requested():
                    cancelled = True
                    execution["deadline_status"] = "cancelled_during_discovery"
                    break
                query_timeout = remaining_timeout(min(4.0, discovery_timeout))
                if query_timeout <= 0:
                    execution["deadline_status"] = "exceeded_during_discovery"
                    break
                if _sync_transport_compat:
                    attempt_results = discovery.fetch(
                        query, allowlist=domains, timeout_s=query_timeout,
                    )
                else:
                    attempt_results, cancelled_during_discovery = await await_with_polling_cancel(
                        discovery.fetch_async(
                            query, allowlist=domains, timeout_s=query_timeout,
                        ),
                        cancellation_requested=cancellation_requested,
                    )
                    if cancelled_during_discovery:
                        cancelled = True
                        execution["deadline_status"] = "cancelled_during_discovery"
                        break
                    attempt_results = attempt_results or []
                attempted += 1
                query_axes.append(query_axis)
                completed_attempt = completed_attempt or (
                    str(discovery.last_receipt.get("execution_status") or "failed") == "completed"
                )
                results.extend(attempt_results)
                discovery.last_receipt.update({
                    "result_count": discovery.last_receipt.get("result_count", len(attempt_results)),
                    "allowlisted_result_count": len(attempt_results),
                    "billing_class": "free", "query_id": f"{source_id}_q{query_index}",
                    "query_purpose": f"official_origin_discovery:{query_axis}",
                })
                receipts.append(_receipt(
                    discovery.last_receipt, run_id=run_id,
                    capability="WEB_DISCOVERY", index=len(receipts) + 1,
                ))
                selected, selection_error = _discovered_origin_for_source(results, source)
                if selected:
                    break
            if cancelled:
                unresolved.append({"source_id": source_id, "reason": "buyer_request_cancelled"})
                source_execution.append(execution)
                break
            unique_results = {
                str(row.get("url") or ""): row for row in results if str(row.get("url") or "")
            }
            execution["discovery_query_count"] = attempted
            execution["discovery_query_axes"] = query_axes
            execution["discovery_result_count"] = len(unique_results)
            execution["discovery_status"] = (
                "completed" if selected
                else "attempted_empty" if completed_attempt
                else "failed"
            )
            if not selected:
                unresolved.append({
                    "source_id": source_id,
                    "reason": selection_error or "official_origin_not_discovered",
                })
                source_execution.append(execution)
                continue
            origin_timeout = remaining_timeout(15.0)
            if origin_timeout <= 0:
                execution["deadline_status"] = "exceeded_before_discovered_origin_fetch"
                unresolved.append({
                    "source_id": source_id, "reason": "research_total_deadline_exceeded",
                })
                source_execution.append(execution)
                continue
            if _sync_transport_compat:
                origin = GovernedOfficialOriginFetcher(max_bytes=8 * 1024 * 1024).fetch(
                    selected, allowlist=domains, timeout_s=origin_timeout,
                    certification_run_id=run_id,
                )
            else:
                origin, cancelled_during_fetch = await await_with_polling_cancel(
                    AsyncGovernedOfficialOriginFetcher(
                        max_bytes=8 * 1024 * 1024,
                    ).fetch_async(
                        selected, allowlist=domains, timeout_s=origin_timeout,
                        certification_run_id=run_id,
                    ),
                    cancellation_requested=cancellation_requested,
                )
                if cancelled_during_fetch:
                    cancelled = True
                    execution["deadline_status"] = "cancelled_during_discovered_origin_fetch"
                    unresolved.append({
                        "source_id": source_id, "reason": "buyer_request_cancelled",
                    })
                    source_execution.append(execution)
                    break
            raw_discovered_receipt = dict(origin["receipt"])
            raw_discovered_receipt.update({
                "billing_class": "free", "origin_content_type": origin.get("content_type"),
                "query_id": source_id, "query_purpose": "discovered_official_origin_fetch",
                "selected_origin_urls": [selected],
            })
            receipts.append(_receipt(
                raw_discovered_receipt, run_id=run_id,
                capability="OFFICIAL_ORIGIN_FETCH", index=len(receipts) + 1,
            ))
            execution.update({
                "origin_selection_mode": (
                    "discovered_novel" if explicit_novel or not canonical
                    else "canonical_fallback_discovered"
                ),
                "selected_origin_url": selected,
            })
            if cancellation_requested and cancellation_requested():
                cancelled = True
                execution["deadline_status"] = "cancelled_after_discovered_origin_fetch"
                unresolved.append({"source_id": source_id, "reason": "buyer_request_cancelled"})
                source_execution.append(execution)
                break

        source_execution.append(execution)
        if origin is None:
            unresolved.append({"source_id": source_id, "reason": "official_origin_unresolved"})
            continue
        raw_origin_receipt = dict(origin["receipt"])
        if origin["status"] != "completed":
            unresolved.append({"source_id": source_id, "reason": origin.get("error")})
            continue
        content_type = str(origin.get("content_type") or "").lower()
        execution["parser_coverage"]["pages_fetched"] = 1
        ownership_required = bool(
            (source.get("publisher_policy") or {}).get(
                "semantic_ownership_verification_required"
            )
        )
        if ownership_required:
            verification = verify_publisher_origin(
                approved_url=selected,
                content=origin["content"],
                purpose=purpose,
            ).model_dump(mode="json")
            execution["publisher_origin_verification"] = verification
            if verification["status"] == "contradicted":
                execution["parser_coverage"]["parse_status"] = "origin_contradicted"
                unresolved.append({
                    "source_id": source_id,
                    "reason": "publisher_origin_semantically_contradicted",
                })
                continue
        parser_type = str(source.get("parser_type") or "")
        if content_type not in _HTML_CONTENT_TYPES or parser_type not in {"html", "html_pdf"}:
            execution["parser_coverage"]["parse_status"] = "content_type_mismatch"
            unresolved.append({"source_id": source_id, "reason": "source_parser_content_type_mismatch"})
            continue
        if active_research_fault() == "zero_parser_yield":
            execution["parser_coverage"]["parse_status"] = (
                "certification_injected_zero_parser_yield"
            )
            unresolved.append({
                "source_id": source_id,
                "reason": "certification_injected_zero_parser_yield",
            })
            continue
        observed_at = str(origin["receipt"].get("observed_at") or datetime.now(timezone.utc).isoformat())
        parse_remaining = remaining_timeout(parser_budget.timeout_ms / 1_000.0)
        if parse_remaining <= 0:
            execution["deadline_status"] = "exceeded_before_parse"
            execution["parser_coverage"]["parse_status"] = "not_attempted_deadline"
            execution["parser_budget"].update({
                "status": "not_attempted_deadline",
                "failure_code": "research_total_deadline_exceeded",
            })
            unresolved.append({
                "source_id": source_id, "reason": "research_total_deadline_exceeded",
            })
            continue
        active_parser_budget = ParserBudget(
            max_input_bytes=parser_budget.max_input_bytes,
            timeout_ms=max(10, round(parse_remaining * 1_000)),
            max_claims=parser_budget.max_claims,
        )
        parser_outcome = await execute_parser_bounded(
            origin["content"],
            lambda: compile_source_claims(
                source_id, origin["content"], observed_at=observed_at,
                citation_url=selected, allow_generic=True,
            ),
            budget=active_parser_budget,
            cancellation_requested=cancellation_requested,
        )
        execution["parser_budget"] = dict(parser_outcome.projection)
        from src.app.observability.pilot_runtime_metrics import official_parser_outcomes_total

        if parser_outcome.status != "completed":
            execution["parser_coverage"]["parse_status"] = parser_outcome.status
            failure_code = str(
                parser_outcome.projection.get("failure_code") or "source_parser_failed"
            )
            official_parser_outcomes_total.labels(
                status=parser_outcome.status, failure_code=failure_code,
            ).inc()
            unresolved.append({"source_id": source_id, "reason": failure_code})
            if parser_outcome.status == "timeout":
                execution["deadline_status"] = "parser_timeout"
            if parser_outcome.status == "cancelled":
                cancelled = True
                execution["deadline_status"] = "cancelled_during_parse"
                break
            continue
        product_rows = [dict(row) for row in parser_outcome.product_claims]
        context_rows = [dict(row) for row in parser_outcome.context_claims]
        product_rows, context_rows, claim_errors = _compiled_claims_allowed(
            source, product_rows, context_rows, observed_at=observed_at, now=current,
        )
        unresolved.extend({"source_id": source_id, "reason": reason} for reason in claim_errors)
        execution["parser_coverage"].update({
            "candidate_claims": len(product_rows) + len(context_rows) + len(claim_errors),
            "accepted_claims": len(product_rows),
            "rejected_claims": len(claim_errors),
            "context_claims": len(context_rows),
            "parse_status": "completed" if (product_rows or context_rows) else "no_scoped_claims",
        })
        official_parser_outcomes_total.labels(
            status="completed" if (product_rows or context_rows) else "zero_yield",
            failure_code="none" if (product_rows or context_rows) else "no_scoped_claims",
        ).inc()
        claims.extend(product_rows)
        context_claims.extend(context_rows)
        observed = _parse_time(observed_at)
        content_hash = str(raw_origin_receipt.get("response_body_hash") or hashlib.sha256(origin["content"]).hexdigest())
        if observed is not None and not claim_errors and (product_rows or context_rows):
            cache.put(OfficialEvidenceCacheEntry(
                key=OfficialEvidenceCacheKey(
                    tenant_id=tenant_id, source_id=source_id,
                    canonical_url=canonical or selected,
                    content_hash=content_hash, parser_version=parser_version,
                    policy_version=policy_version,
                ),
                content_type=content_type, observed_at=observed,
                freshness_sla_hours=int(source["freshness_sla_hours"]),
                claims=tuple(dict(row) for row in product_rows),
                context_claims=tuple(dict(row) for row in context_rows),
            ))
        if not product_rows and not context_rows:
            unresolved.append({"source_id": source_id, "reason": "no_recognized_scoped_claims"})
    deduped = list({row["claim_id"]: row for row in claims}.values())
    evidence_outcome = (
        "product_requirements" if deduped
        else "context_only" if context_claims
        else "unresolved"
    )
    if evidence_outcome == "context_only":
        unresolved.append({
            "source_id": None,
            "reason": "no_product_requirement_claims",
        })
    external_calls = sum(1 for row in receipts if row["external_call_dispatched"])
    discovery_calls = sum(
        1 for row in receipts
        if row["provider_capability"] == "WEB_DISCOVERY" and row["external_call_dispatched"]
    )
    official_fetches = sum(
        1 for row in receipts
        if row["provider_capability"] == "OFFICIAL_ORIGIN_FETCH"
        and row["external_call_dispatched"]
    )
    cache_hits = sum(1 for row in receipts if row["cache_status"] == "fresh_hit")
    execution_mode = (
        "live_network" if any(row["network_execution"] for row in receipts)
        else "evidence_cache" if cache_hits
        else "not_executed"
    )
    evidence_ladder = _evidence_ladder_projection(
        receipts=receipts, source_execution=source_execution,
        evidence_outcome=evidence_outcome, search_configured=bool(search_url_template),
    )
    return {
        "schema_version": "official-workload-research-v1",
        "run_id": run_id, "purpose": purpose,
        "research_plan_id": plan_id,
        "hypothesis_ids": list(hypothesis_ids or []),
        "source_ids": [str(source.get("source_id") or "") for source in sources],
        "claims": deduped, "context_claims": context_claims,
        "unresolved": unresolved, "receipts": receipts,
        "source_execution": source_execution,
        "evidence_ladder": evidence_ladder,
        "evidence_outcome": evidence_outcome,
        "provider_accounting": {
            "external_calls": external_calls, "discovery_calls": discovery_calls,
            "official_origin_fetches": official_fetches,
            "cache_hits": cache_hits, "paid_calls": 0,
        },
        "execution_mode": execution_mode,
        "status": "cancelled" if cancelled else "completed",
        "cancellation": {
            "requested": cancelled,
            "remaining_sources_not_dispatched": max(
                0, min(4, len(sources)) - len(source_execution),
            ),
        },
        "runtime": {
            "total_timeout_s": max(0.0, float(total_timeout_s)),
            "parser_budget": {
                "max_input_bytes": parser_budget.max_input_bytes,
                "timeout_ms": parser_budget.timeout_ms,
                "max_claims": parser_budget.max_claims,
            },
            "elapsed_ms": round((time.monotonic() - started_monotonic) * 1000, 3),
            "deadline_exceeded": any(
                row.get("deadline_status") != "within_deadline" for row in source_execution
            ),
        },
        "authority_rule": "discovery finds; source-specific official parser establishes scoped claims",
        "certification_fault_profile": active_research_fault(),
    }


def research_official_sources_sync(
    purpose: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Explicit compatibility bridge for scripts/tests outside an event loop.

    Buyer-facing HTTP paths must await ``research_official_sources`` so active
    sockets are cancelled with the request. This bridge intentionally refuses
    to nest an event loop instead of silently blocking one.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(research_official_sources(
            purpose, **kwargs, _sync_transport_compat=True,
        ))
    raise RuntimeError("research_official_sources_sync_called_from_async_context")


def research_official_workload(
    purpose: str, *, search_url_template: str, workload: str = "ot_cyber_range",
) -> dict[str, Any]:
    """Deprecated workload-label wrapper retained for compatibility tests."""

    result = research_official_sources_sync(
        purpose, search_url_template=search_url_template,
        sources=list(governed_sources_for_workload(workload)),
    )
    result["workload"] = workload
    return result


def positions(projection: dict[str, Any]) -> dict[str, int]:
    for shelf in projection.get("shelves") or []:
        if shelf.get("scope_id") == "shared" or "shared" in str(shelf.get("shelf_id")):
            rows = [*(shelf.get("initial") or []), *(shelf.get("next_page") or [])]
            return {str(row["product"]["sku"]): index + 1 for index, row in enumerate(rows)}
    return {}


def ranking_delta(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    old, new = positions(before), positions(after)
    def indexed(projection: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for shelf in projection.get("shelves") or []:
            if str(shelf.get("scope_id") or shelf.get("shelf_id") or "") != "shared":
                continue
            for product in [*(shelf.get("initial") or []), *(shelf.get("next_page") or [])]:
                sku = str((product.get("product") or {}).get("sku") or "")
                if sku and sku not in result:
                    result[sku] = product
        return result

    old_products, new_products = indexed(before), indexed(after)

    def reason_for(sku: str) -> str:
        previous, current = old_products.get(sku), new_products.get(sku)
        if previous is None:
            return "entered the shared shortlist after accepted official evidence was compiled"
        if current is None:
            return "left the shared shortlist after accepted official evidence was compiled"
        reasons: list[str] = []
        if previous.get("fit_status") != current.get("fit_status"):
            reasons.append(
                f"fit changed from {previous.get('fit_status') or 'unknown'} "
                f"to {current.get('fit_status') or 'unknown'}"
            )
        resolved = sorted(set(previous.get("unknowns") or []) - set(current.get("unknowns") or []))
        if resolved:
            reasons.append("resolved evidence gaps: " + ", ".join(resolved))
        added_meets = sorted(set(current.get("meets") or []) - set(previous.get("meets") or []))
        if added_meets:
            reasons.append("newly evidenced meets: " + ", ".join(added_meets))
        added_misses = sorted(set(current.get("misses") or []) - set(previous.get("misses") or []))
        if added_misses:
            reasons.append("newly verified minimum misses: " + ", ".join(added_misses))
        return "; ".join(reasons) or "relative order changed after deterministic evidence reduction"

    rows = []
    for sku in sorted(set(old) | set(new)):
        if old.get(sku) == new.get(sku):
            continue
        rows.append({
            "sku": sku, "before": old.get(sku), "after": new.get(sku),
            "movement": (old.get(sku) or 999) - (new.get(sku) or 999),
            "reason": reason_for(sku),
        })
    return sorted(rows, key=lambda row: (-abs(row["movement"]), row["sku"]))


__all__ = [
    "compile_source_claims", "ranking_delta", "research_official_sources",
    "research_official_workload",
]
