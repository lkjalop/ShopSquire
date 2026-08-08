"""Governed discovery, official-origin parsing and typed claim compilation.

The service is intentionally workload-light.  Source applicability comes from the
reviewed registry; parsers are source-specific because publisher documents are
contracts, not interchangeable prose.  Discovery snippets are never parsed.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from src.app.adapters.external_research_httpx import HttpxResearchFetcher
from src.app.adapters.official_origin_httpx import GovernedOfficialOriginFetcher
from src.app.services.official_source_governance import governed_sources_for_workload
from src.app.services.recommendation_core.research_contracts import ProviderExecutionReceipt


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


def compile_source_claims(
    source_id: str, content: bytes, *, observed_at: str, citation_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile only claims recognized by the selected source-specific parser."""

    parser = _SOURCE_PARSERS.get(source_id)
    if parser is None:
        return [], []
    return parser(source_id, _html_text(content).casefold(), observed_at, citation_url)


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
        execution_status=raw.get("execution_status", "failed"), fixture=False,
        network_execution=bool(raw.get("network_execution")),
        external_call_dispatched=bool(raw.get("external_call_dispatched")),
        cache_status=raw.get("cache_status", "miss"),
        billing_class=raw.get("billing_class", "unknown"),
        started_at=raw.get("started_at"), completed_at=raw.get("completed_at"),
        http_status=raw.get("http_status"), result_count=raw.get("result_count"),
        allowlisted_result_count=raw.get("allowlisted_result_count"),
        response_body_hash=raw.get("response_body_hash"),
        origin_content_type=raw.get("origin_content_type"),
        selected_origin_urls=list(raw.get("selected_origin_urls") or []),
        origin_observed_at=raw.get("observed_at"), rejection_reason=raw.get("error"),
    )
    return model.model_dump(mode="json")


def _source_query(source: dict[str, Any]) -> str:
    """Build a bounded discovery query from governed manifest data only."""

    domain = str((source.get("allowed_domains") or [""])[0])
    publisher = str(source.get("publisher") or "official publisher")
    artefact = str((source.get("artefact_patterns") or [publisher])[0])
    claim_types = set(source.get("allowed_claim_types") or [])
    purpose = (
        "system requirements compatibility"
        if claim_types.intersection({"minimum_requirements", "recommended_requirements", "compatibility"})
        else "workload scope"
    )
    return f"site:{domain} {artefact} {publisher} official {purpose}"[:240]


def research_official_sources(
    purpose: str,
    *,
    search_url_template: str,
    sources: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    plan_id: str | None = None,
    hypothesis_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Execute an already-authorized case plan against approved source records."""

    run_id = f"research-{uuid.uuid4().hex[:12]}"
    receipts: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    context_claims: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for source in sources[:4]:
        source_id = str(source["source_id"])
        query = _source_query(source)
        domains = list(source["allowed_domains"])
        discovery = HttpxResearchFetcher(
            search_url_template=search_url_template, allow_private=True,
        )
        results = discovery.fetch(query, allowlist=domains, timeout_s=12)
        discovery.last_receipt.update({
            "result_count": len(results), "allowlisted_result_count": len(results),
            "billing_class": "free", "query_id": source_id,
            "query_purpose": "official_origin_discovery",
        })
        receipts.append(_receipt(
            discovery.last_receipt, run_id=run_id,
            capability="WEB_DISCOVERY", index=len(receipts) + 1,
        ))
        canonical = str((source.get("canonical_entrypoints") or [""])[0])
        # A reviewed canonical origin wins over discovery ordering. Discovery proves
        # reachability/findability; it cannot silently replace a publisher contract.
        selected = canonical or next((str(row.get("url")) for row in results if row.get("url")), "")
        if not selected or (urlparse(selected).hostname or "").lower() not in domains:
            selected = canonical
        origin = GovernedOfficialOriginFetcher(max_bytes=8 * 1024 * 1024).fetch(
            selected, allowlist=domains, timeout_s=15, certification_run_id=run_id,
        )
        raw_origin_receipt = dict(origin["receipt"])
        raw_origin_receipt["billing_class"] = "free"
        raw_origin_receipt["origin_content_type"] = origin.get("content_type")
        raw_origin_receipt["query_id"] = source_id
        raw_origin_receipt["query_purpose"] = "official_requirement_fetch"
        raw_origin_receipt["selected_origin_urls"] = [selected]
        receipts.append(_receipt(
            raw_origin_receipt, run_id=run_id,
            capability="OFFICIAL_ORIGIN_FETCH", index=len(receipts) + 1,
        ))
        if origin["status"] != "completed":
            unresolved.append({"source_id": source_id, "reason": origin.get("error")})
            continue
        observed_at = str(origin["receipt"].get("observed_at") or datetime.now(timezone.utc).isoformat())
        product_rows, context_rows = compile_source_claims(
            source_id, origin["content"], observed_at=observed_at, citation_url=selected,
        )
        claims.extend(product_rows)
        context_claims.extend(context_rows)
        if not product_rows and not context_rows:
            unresolved.append({"source_id": source_id, "reason": "no_recognized_scoped_claims"})
    deduped = list({row["claim_id"]: row for row in claims}.values())
    return {
        "schema_version": "official-workload-research-v1",
        "run_id": run_id, "purpose": purpose,
        "research_plan_id": plan_id,
        "hypothesis_ids": list(hypothesis_ids or []),
        "source_ids": [str(source.get("source_id") or "") for source in sources],
        "claims": deduped, "context_claims": context_claims,
        "unresolved": unresolved, "receipts": receipts,
        "provider_accounting": {
            "external_calls": sum(1 for row in receipts if row["external_call_dispatched"]),
            "paid_calls": 0,
        },
        "execution_mode": "live_network",
        "authority_rule": "discovery finds; source-specific official parser establishes scoped claims",
    }


def research_official_workload(
    purpose: str, *, search_url_template: str, workload: str = "ot_cyber_range",
) -> dict[str, Any]:
    """Deprecated workload-label wrapper retained for compatibility tests."""

    result = research_official_sources(
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
    rows = []
    for sku in sorted(set(old) | set(new)):
        if old.get(sku) == new.get(sku):
            continue
        rows.append({
            "sku": sku, "before": old.get(sku), "after": new.get(sku),
            "movement": (old.get(sku) or 999) - (new.get(sku) or 999),
            "reason": "official evidence changed verified fit, gaps, or operating-system compatibility",
        })
    return sorted(rows, key=lambda row: (-abs(row["movement"]), row["sku"]))


__all__ = [
    "compile_source_claims", "ranking_delta", "research_official_sources",
    "research_official_workload",
]
