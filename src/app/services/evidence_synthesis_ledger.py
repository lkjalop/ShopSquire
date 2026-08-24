"""Case-bound intent, source receipts and deterministic claim adjudication."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field


ClaimStatus = Literal["accepted", "rejected", "contradicted", "unresolved"]


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


class EvidenceIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "evidence-intent.v1"
    intent_id: str
    case_id: str
    case_revision: int = Field(ge=1)
    query: str
    query_hash: str
    purpose: str
    consent_receipt: dict[str, Any]
    evidence_version: str
    evidence_subject_identity: dict[str, Any]
    product_configuration_binding: dict[str, Any]


class EvidenceSourceReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    source_class: Literal["official", "distributor", "retailer", "commentary", "unknown"]
    publisher: str | None = None
    url: str | None = None
    exact_query_or_request: str | None = None
    retrieval_time: str | None = None
    execution_status: str
    query_hash: str | None = None
    response_receipt_hash: str | None = None
    freshness_sla_hours: int | None = None
    publisher_ownership_score: float = Field(ge=0.0, le=1.0)
    publisher_ownership_threshold: float = Field(ge=0.0, le=1.0)
    publisher_ownership_status: str
    billing_class: str
    provider_cost_minor: int = Field(ge=0)
    paid_call_count: int = Field(ge=0)
    failure_reason: str | None = None


class ClaimAdjudication(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    status: ClaimStatus
    claim_type: str
    attribute_key: str | None = None
    value: Any = None
    source_ids: list[str]
    freshness_status: str
    applicable_version: str
    case_revision: int
    evidence_subject_identity: dict[str, Any]
    product_configuration_binding: dict[str, Any]
    reason: str


class EvidenceSynthesisLedger(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "evidence-synthesis-ledger.v1"
    ledger_id: str
    evidence_intent: EvidenceIntent
    sources: list[EvidenceSourceReceipt]
    claims: list[ClaimAdjudication]
    claim_coverage: dict[str, int]
    contradictions: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    provider_accounting: dict[str, Any]
    decision_trace_projection: dict[str, Any]
    seal_sha256: str


def _source_class(source: dict[str, Any]) -> str:
    value = str(source.get("source_class") or "official").strip().lower()
    return value if value in {"official", "distributor", "retailer", "commentary"} else "unknown"


def build_evidence_synthesis_ledger(
    *,
    case_id: str,
    case_revision: int,
    query: str,
    purpose: str,
    consent_receipt: dict[str, Any],
    research: dict[str, Any],
    approved_sources: Sequence[dict[str, Any]],
    candidate_configuration_ids: Sequence[str],
    minimum_publisher_ownership_score: float = 0.8,
) -> EvidenceSynthesisLedger:
    """Adjudicate one research run without granting product or commerce authority."""

    if consent_receipt.get("authorized") is not True:
        raise ValueError("research_consent_receipt_required")
    consent_time = _time(consent_receipt.get("recorded_at"))
    if consent_time is None:
        raise ValueError("research_consent_time_requires_timezone")
    run_id = str(research.get("run_id") or "unversioned-research")
    evidence_version = f"{run_id}:case-revision:{case_revision}"
    subject_identity = {
        "retained_purpose_hash": _hash(purpose),
        "hypothesis_ids": sorted(str(row) for row in research.get("hypothesis_ids") or []),
        "binding_status": "case_purpose_and_hypotheses_bound",
    }
    configuration_ids = sorted({str(row) for row in candidate_configuration_ids if str(row)})
    product_binding = {
        "candidate_configuration_ids": configuration_ids,
        "binding_status": (
            "candidate_set_bound_not_claim_authority"
            if configuration_ids else "no_product_configuration_bound"
        ),
        "identity_authority": "separate_catalog_identity_verification_required",
    }
    intent = EvidenceIntent(
        intent_id=f"evi-{_hash([case_id, case_revision, query, purpose])[:20]}",
        case_id=case_id,
        case_revision=case_revision,
        query=query,
        query_hash=_hash(query),
        purpose=purpose,
        consent_receipt=dict(consent_receipt),
        evidence_version=evidence_version,
        evidence_subject_identity=subject_identity,
        product_configuration_binding=product_binding,
    )

    policies = {str(row.get("source_id") or ""): dict(row) for row in approved_sources}
    executions = {
        str(row.get("source_id") or ""): dict(row)
        for row in research.get("source_execution") or []
    }
    provider_receipts = list(research.get("receipts") or [])
    source_rows: list[EvidenceSourceReceipt] = []
    ownership_by_source: dict[str, float] = {}
    for source_id in sorted(set(policies) | set(executions)):
        policy = policies.get(source_id, {})
        execution = executions.get(source_id, {})
        receipt = next((
            row for row in reversed(provider_receipts)
            if str(row.get("query_id") or "") == source_id
        ), {})
        selected_url = str(
            execution.get("selected_origin_url")
            or (receipt.get("selected_origin_urls") or [None])[0]
            or policy.get("canonical_entrypoints", [None])[0]
            or ""
        ) or None
        host = str(urlparse(selected_url or "").hostname or "").lower()
        allowed = {str(row).lower() for row in policy.get("allowed_domains") or []}
        enrolled_direct = bool(
            policy.get("review_status") == "approved"
            and (policy.get("publisher_policy") or {}).get("direct_origin_required") is True
            and host
            and any(host == domain or host.endswith("." + domain) for domain in allowed)
        )
        ownership_score = 1.0 if enrolled_direct else 0.0
        ownership_by_source[source_id] = ownership_score
        completed = str(receipt.get("execution_status") or "") == "completed"
        retrieval_time = receipt.get("origin_observed_at") or receipt.get("completed_at")
        started_at = _time(receipt.get("started_at"))
        dispatched_before_consent = bool(
            receipt.get("external_call_dispatched") and started_at and started_at < consent_time
        )
        status = str(receipt.get("execution_status") or execution.get("deadline_status") or "not_executed")
        failure_reason = (
            "network_dispatch_preceded_consent" if dispatched_before_consent
            else receipt.get("rejection_reason")
            or execution.get("discovery_reason") if not completed else None
        )
        source_rows.append(EvidenceSourceReceipt(
            source_id=source_id,
            source_class=_source_class(policy),
            publisher=policy.get("publisher") or execution.get("publisher"),
            url=selected_url,
            exact_query_or_request=(
                selected_url if execution.get("origin_selection_mode") != "discovered_novel"
                else " | ".join(execution.get("discovery_queries") or []) or None
            ),
            retrieval_time=retrieval_time,
            execution_status=status,
            query_hash=receipt.get("query_hash"),
            response_receipt_hash=receipt.get("response_body_hash"),
            freshness_sla_hours=policy.get("freshness_sla_hours"),
            publisher_ownership_score=ownership_score,
            publisher_ownership_threshold=minimum_publisher_ownership_score,
            publisher_ownership_status=(
                "accepted_enrolled_direct_origin"
                if ownership_score >= minimum_publisher_ownership_score
                else "rejected_below_threshold"
            ),
            billing_class=str(receipt.get("billing_class") or "unknown"),
            provider_cost_minor=0,
            paid_call_count=0,
            failure_reason=str(failure_reason) if failure_reason else None,
        ))

    raw_claims = [dict(row) for row in research.get("claims") or []]
    conflict_groups: dict[str, list[dict[str, Any]]] = {}
    for claim in raw_claims:
        key = str(claim.get("attribute_key") or claim.get("attribute") or claim.get("claim_type") or "")
        conflict_groups.setdefault(key, []).append(claim)
    contradicted_ids: set[str] = set()
    contradictions: list[dict[str, Any]] = []
    for key, rows in conflict_groups.items():
        values = {_hash([row.get("operator"), row.get("value"), row.get("unit")]) for row in rows}
        sources = {str(row.get("source_id") or "") for row in rows}
        if len(values) > 1 and len(sources) > 1:
            ids = [str(row.get("claim_id") or _hash(row)[:20]) for row in rows]
            contradicted_ids.update(ids)
            contradictions.append({
                "attribute_key": key, "claim_ids": ids,
                "source_ids": sorted(sources), "status": "unresolved_contradiction",
            })

    claim_rows: list[ClaimAdjudication] = []
    for claim in raw_claims:
        claim_id = str(claim.get("claim_id") or _hash(claim)[:20])
        source_id = str(claim.get("source_id") or "unknown")
        freshness = str(claim.get("freshness_status") or "unknown")
        if claim_id in contradicted_ids:
            status: ClaimStatus = "contradicted"
            reason = "material_value_conflict_across_sources"
        elif ownership_by_source.get(source_id, 0.0) < minimum_publisher_ownership_score:
            status = "rejected"
            reason = "publisher_ownership_below_minimum_threshold"
        elif freshness != "fresh":
            status = "rejected"
            reason = "evidence_not_fresh"
        else:
            status = "accepted"
            reason = "fresh_claim_from_enrolled_direct_origin"
        claim_rows.append(ClaimAdjudication(
            claim_id=claim_id,
            status=status,
            claim_type=str(claim.get("claim_type") or "unknown"),
            attribute_key=(
                str(claim.get("attribute_key") or claim.get("attribute"))
                if claim.get("attribute_key") or claim.get("attribute") else None
            ),
            value=claim.get("value"),
            source_ids=[source_id],
            freshness_status=freshness,
            applicable_version=evidence_version,
            case_revision=case_revision,
            evidence_subject_identity=subject_identity,
            product_configuration_binding=product_binding,
            reason=reason,
        ))
    gaps = [dict(row) for row in research.get("unresolved") or []]
    for index, gap in enumerate(gaps):
        claim_rows.append(ClaimAdjudication(
            claim_id=f"gap-{index + 1}-{_hash(gap)[:12]}",
            status="unresolved",
            claim_type=str(gap.get("claim_type") or "evidence_gap"),
            source_ids=[str(gap.get("source_id") or "unknown")],
            freshness_status="not_applicable",
            applicable_version=evidence_version,
            case_revision=case_revision,
            evidence_subject_identity=subject_identity,
            product_configuration_binding=product_binding,
            reason=str(gap.get("reason") or "unresolved_evidence_gap"),
        ))
    coverage = {status: sum(row.status == status for row in claim_rows) for status in (
        "accepted", "rejected", "contradicted", "unresolved",
    )}
    accounting = dict(research.get("provider_accounting") or {})
    accounting.setdefault("provider_cost_minor", 0)
    projection = {
        "research_execution": str(research.get("execution_mode") or "not_executed"),
        "evidence_status": (
            "blocked_contradiction" if coverage["contradicted"]
            else "accepted_with_gaps" if coverage["accepted"] and coverage["unresolved"]
            else "accepted" if coverage["accepted"]
            else "unresolved"
        ),
        "freshness": (
            "fresh" if coverage["accepted"] and not coverage["rejected"] else "incomplete"
        ),
        "decision_status": (
            "requirements_eligible" if coverage["accepted"] and not coverage["contradicted"]
            else "provisional_only"
        ),
        "commerce_authority": "none",
        "case_revision": case_revision,
        "evidence_version": evidence_version,
    }
    raw_ledger = {
        "intent": intent.model_dump(mode="json"),
        "sources": [row.model_dump(mode="json") for row in source_rows],
        "claims": [row.model_dump(mode="json") for row in claim_rows],
        "projection": projection,
    }
    return EvidenceSynthesisLedger(
        ledger_id=f"esl-{_hash(raw_ledger)[:20]}",
        evidence_intent=intent,
        sources=source_rows,
        claims=claim_rows,
        claim_coverage=coverage,
        contradictions=contradictions,
        gaps=gaps,
        provider_accounting=accounting,
        decision_trace_projection=projection,
        seal_sha256=_hash(raw_ledger),
    )


__all__ = [
    "ClaimAdjudication", "EvidenceIntent", "EvidenceSourceReceipt",
    "EvidenceSynthesisLedger", "build_evidence_synthesis_ledger",
]
