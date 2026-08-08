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
    statement: str, observed_at: str, citation_url: str,
) -> dict[str, Any]:
    digest = hashlib.sha256(
        f"{source_id}|{attribute}|{operator}|{value}|{citation_url}".encode()
    ).hexdigest()[:16]
    return {
        "claim_id": f"official-{digest}",
        "attribute": attribute,
        "operator": operator,
        "value": value,
        "unit": unit,
        "requirement_class": "minimum",
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


def compile_source_claims(
    source_id: str, content: bytes, *, observed_at: str, citation_url: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compile only explicitly recognized publisher statements."""
    text = _html_text(content)
    folded = text.casefold()
    product_claims: list[dict[str, Any]] = []
    context_claims: list[dict[str, Any]] = []
    if source_id == "factory_io_official_docs":
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
    elif source_id == "microsoft_learn_hyperv":
        if "at least 4 gb of ram" in folded:
            product_claims.append(_claim(
                source_id, "ram_gb", ">=", 4, unit="GB",
                statement="Microsoft documents at least 4 GB for the host and notes that simultaneous VMs need additional memory.",
                observed_at=observed_at, citation_url=citation_url,
            ))
        if "windows 11 professional or enterprise" in folded:
            product_claims.append(_claim(
                source_id, "operating_system", "one_of",
                ["Windows 11 Pro", "Windows 11 Enterprise"],
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
                product_claims.append(_claim(
                    source_id, attribute, "equals", True,
                    claim_type="compatibility", statement=statement,
                    observed_at=observed_at, citation_url=citation_url,
                ))
    elif source_id in {"nist_digital_twin_cybersecurity", "mitre_attack_ics"}:
        # These publishers establish scope/topology, never a laptop floor.
        markers = {
            "nist_digital_twin_cybersecurity": "digital twin",
            "mitre_attack_ics": "ics",
        }
        marker = markers[source_id]
        if marker in folded:
            context_claims.append({
                "claim_id": f"context-{source_id}", "source_id": source_id,
                "claim_type": "workload_scope", "status": "corroborated",
                "statement": (
                    "Official material corroborates the workload scope; it does not establish a hardware floor."
                ),
                "citation_url": citation_url, "observed_at": observed_at,
                "authority_status": "verified_official", "freshness_status": "fresh",
            })
    return product_claims, context_claims


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
        query_hash=raw.get("query_hash"), obligation_ids=["workload-research"],
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
        origin_observed_at=raw.get("observed_at"), rejection_reason=raw.get("error"),
    )
    return model.model_dump(mode="json")


def research_official_workload(
    purpose: str, *, search_url_template: str, workload: str = "ot_cyber_range",
) -> dict[str, Any]:
    sources = governed_sources_for_workload(workload)
    run_id = f"research-{uuid.uuid4().hex[:12]}"
    receipts: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    context_claims: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    query_templates = {
        "nist_digital_twin_cybersecurity": "site:csrc.nist.gov digital twin cybersecurity NIST IR 8356",
        "mitre_attack_ics": "site:attack.mitre.org ATT&CK ICS matrix",
        "factory_io_official_docs": "site:docs.factoryio.com Factory I/O system requirements",
        "microsoft_learn_hyperv": "site:learn.microsoft.com Hyper-V host hardware requirements",
    }
    for source in sources[:4]:
        source_id = str(source["source_id"])
        query = query_templates.get(source_id, f"{source['publisher']} official requirements")
        domains = list(source["allowed_domains"])
        discovery = HttpxResearchFetcher(
            search_url_template=search_url_template, allow_private=True,
        )
        results = discovery.fetch(query, allowlist=domains, timeout_s=12)
        discovery.last_receipt.update({
            "result_count": len(results), "allowlisted_result_count": len(results),
            "billing_class": "free",
        })
        receipts.append(_receipt(
            discovery.last_receipt, run_id=run_id,
            capability="WEB_DISCOVERY", index=len(receipts) + 1,
        ))
        canonical = str((source.get("canonical_entrypoints") or [""])[0])
        selected = next((str(row.get("url")) for row in results if row.get("url")), canonical)
        if not selected or (urlparse(selected).hostname or "").lower() not in domains:
            selected = canonical
        origin = GovernedOfficialOriginFetcher(max_bytes=8 * 1024 * 1024).fetch(
            selected, allowlist=domains, timeout_s=15, certification_run_id=run_id,
        )
        raw_origin_receipt = dict(origin["receipt"])
        raw_origin_receipt["billing_class"] = "free"
        raw_origin_receipt["origin_content_type"] = origin.get("content_type")
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
        "run_id": run_id, "purpose": purpose, "workload": workload,
        "claims": deduped, "context_claims": context_claims,
        "unresolved": unresolved, "receipts": receipts,
        "provider_accounting": {
            "external_calls": sum(1 for row in receipts if row["external_call_dispatched"]),
            "paid_calls": 0,
        },
        "execution_mode": "live_network",
        "authority_rule": "discovery finds; source-specific official parser establishes scoped claims",
    }


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
    "compile_source_claims", "ranking_delta", "research_official_workload",
]
