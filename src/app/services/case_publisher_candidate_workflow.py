"""Durable case-only governance for open-world publisher candidates."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence
from urllib.parse import urlparse

from sqlalchemy import select

from src.app.models.orm import RequirementProposal, ShoppingCasePublisherCandidate


CASE_ALLOWED_CLAIM_TYPES = frozenset({
    "minimum_requirements", "recommended_requirements", "target_requirements",
    "compatibility", "operating_system_support", "hardware_certification",
})
CASE_FORBIDDEN_CLAIM_TYPES = (
    "exact_product_fit", "purchase_authority", "supplier_authority",
    "benchmark_performance", "security_assurance", "commercial_availability",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def candidate_id(*, case_id: str, url: str) -> str:
    digest = hashlib.sha256(f"{case_id}|{url}".encode("utf-8")).hexdigest()[:20]
    return f"pubcand-{digest}"


def persist_discovered_candidates(
    db,
    *,
    tenant_id: str,
    case_id: str,
    uid: str,
    candidates: Sequence[dict[str, Any]],
    receipts: Sequence[dict[str, Any]],
) -> list[ShoppingCasePublisherCandidate]:
    """Upsert discovery observations without changing their authority."""

    receipt_ids = [
        str(row.get("receipt_id") or row.get("query_hash") or "")
        for row in receipts if row.get("receipt_id") or row.get("query_hash")
    ]
    all_axes = [str(row.get("query_axis") or "") for row in receipts if row.get("query_axis")]
    persisted: list[ShoppingCasePublisherCandidate] = []
    for raw in candidates[:12]:
        url = str(raw.get("url") or "").strip()
        parsed = urlparse(url)
        domain = str(parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme != "https" or not domain or parsed.username or parsed.password:
            continue
        row = db.execute(select(ShoppingCasePublisherCandidate).where(
            ShoppingCasePublisherCandidate.tenant_id == tenant_id,
            ShoppingCasePublisherCandidate.case_id == case_id,
            ShoppingCasePublisherCandidate.url == url,
        )).scalar_one_or_none()
        if row is None:
            row = ShoppingCasePublisherCandidate(
                candidate_id=candidate_id(case_id=case_id, url=url),
                tenant_id=tenant_id, case_id=case_id, uid=uid, url=url,
                domain=domain, title=str(raw.get("title") or domain)[:200],
                query_axes_json=list(dict.fromkeys(raw.get("query_axes") or all_axes)),
                discovery_receipt_ids_json=list(dict.fromkeys(receipt_ids)),
                status="discovered", authority_status="not_accepted",
                allowed_claim_types_json=[], version=1,
                created_at=_now(), updated_at=_now(),
            )
            db.add(row)
        persisted.append(row)
    db.flush()
    return persisted


def approve_case_candidate(
    row: ShoppingCasePublisherCandidate,
    *,
    uid: str,
    expected_version: int,
    idempotency_key: str,
    allowed_claim_types: Sequence[str],
) -> tuple[ShoppingCasePublisherCandidate | None, str | None]:
    if row.uid != uid:
        return None, "publisher_candidate_not_owned"
    if row.approval_idempotency_key == idempotency_key and row.status in {"approved", "researched"}:
        return row, None
    if row.approval_idempotency_key and row.approval_idempotency_key != idempotency_key:
        return None, "publisher_candidate_already_approved"
    if row.version != expected_version:
        return None, "stale_publisher_candidate"
    requested = set(allowed_claim_types)
    if not requested or not requested <= CASE_ALLOWED_CLAIM_TYPES:
        return None, "publisher_claim_policy_invalid"
    row.status = "approved"
    row.authority_status = "buyer_attested_case_only"
    row.approval_scope = "case_only"
    row.allowed_claim_types_json = sorted(requested)
    row.approved_by = uid
    row.approval_idempotency_key = idempotency_key
    row.version += 1
    row.updated_at = _now()
    return row, None


def case_source_policy(row: ShoppingCasePublisherCandidate, *, purpose: str) -> dict[str, Any]:
    """Build a one-case source policy; this never enrolls the domain globally."""

    return {
        "source_id": f"case_source_{row.candidate_id.replace('-', '_')}",
        "publisher": row.title or row.domain,
        "review_status": "approved",
        "reviewed_by": row.approved_by,
        "allowed_domains": [row.domain],
        "canonical_entrypoints": [row.url],
        "allowed_claim_types": list(row.allowed_claim_types_json),
        "forbidden_claim_types": list(CASE_FORBIDDEN_CLAIM_TYPES),
        "applicability": {
            "workloads": ["case_open_world"],
            "scope": purpose,
            "resolution_owner": "buyer",
            "exclusions": ["global publisher enrollment", "exact product fit"],
        },
        "freshness_sla_hours": 24,
        "parser_type": "html",
        "publisher_policy": {
            "policy_ref": f"case-only:{row.case_id}:{row.version}",
            "direct_origin_required": True,
            "search_snippets_forbidden": True,
            "approval_scope": "case_only",
            "publisher_ownership_status": "buyer_attested_not_independently_verified",
        },
        "cache_policy": {"store_source_text": False, "store_hashes_and_claims_only": True},
    }


def case_review_claims(
    claims: Sequence[dict[str, Any]], *, candidate: ShoppingCasePublisherCandidate,
) -> list[dict[str, Any]]:
    """Project critic-accepted origin claims into the existing buyer review contract."""

    rows: list[dict[str, Any]] = []
    for raw in claims:
        item = dict(raw)
        claim_type = str(item.get("claim_type") or "").strip()
        citation = urlparse(str(item.get("citation_url") or "").strip())
        citation_host = str(citation.hostname or "").lower().rstrip(".")
        candidate_host = str(candidate.domain or "").lower().rstrip(".")
        citation_matches_approved_origin = bool(
            citation.scheme == "https"
            and citation_host
            and candidate_host
            and (
                citation_host == candidate_host
                or citation_host.endswith("." + candidate_host)
            )
            and not citation.username
            and not citation.password
        )
        if (
            claim_type not in set(candidate.allowed_claim_types_json or [])
            or claim_type in CASE_FORBIDDEN_CLAIM_TYPES
            or not citation_matches_approved_origin
        ):
            # The research service and its parser/critic are separate trust
            # boundaries. Re-check the case-only claim policy here before a
            # row can become buyer-reviewable evidence or influence ranking.
            continue
        item.update({
            "subject": "buyer_workload_requirement",
            "constraint_tier": "preferred",
            "source_reference": candidate.url,
            "source_excerpt": str(
                item.get("quoted_evidence_span") or item.get("statement") or ""
            )[:500],
            "evidence_class": "official_case_source",
            "extraction_confidence": 1.0,
            "authority_status": "verified_case_origin",
            "acceptance_status": "pending_buyer_review",
            "approval_scope": "case_only",
            "publisher_ownership_status": "buyer_attested_not_independently_verified",
        })
        rows.append(item)
    return rows


def execute_case_candidate_research(
    db,
    *,
    candidate: ShoppingCasePublisherCandidate,
    case: Any,
    tenant_id: str,
    uid: str,
    expected_version: int,
    idempotency_key: str,
    allowed_claim_types: Sequence[str],
) -> tuple[dict[str, Any] | None, str | None]:
    """Approve, fetch, extract, and persist reviewable claims for one case.

    This is the application-service seam for the open-world vertical. It never
    grants product-fit, supplier-send, or cart authority.
    """

    if candidate.approval_idempotency_key == idempotency_key and candidate.research_result_json:
        return dict(candidate.research_result_json), None
    approved, error = approve_case_candidate(
        candidate, uid=uid, expected_version=expected_version,
        idempotency_key=idempotency_key, allowed_claim_types=allowed_claim_types,
    )
    if error or approved is None:
        return None, error or "publisher_candidate_approval_failed"

    from src.app.services.official_workload_research import (
        DEFAULT_OFFICIAL_EVIDENCE_CACHE,
        research_official_sources,
    )

    source = case_source_policy(
        approved, purpose=case.retained_purpose or "Buyer requested workload",
    )
    research = research_official_sources(
        case.retained_purpose or "Buyer requested workload",
        search_url_template="", sources=[source], tenant_id=tenant_id,
        evidence_cache=DEFAULT_OFFICIAL_EVIDENCE_CACHE, total_timeout_s=12.0,
    )
    from src.app.services.commerce_feature_readiness import (
        record_external_research_runtime_observation,
    )

    record_external_research_runtime_observation(research)
    claims = case_review_claims(research.get("claims") or [], candidate=approved)
    proposal: RequirementProposal | None = None
    if claims:
        proposal = RequirementProposal(
            proposal_id=f"rp-{uuid.uuid4().hex[:20]}", case_id=case.case_id,
            tenant_id=tenant_id, uid=uid, version=1, status="pending_review",
            source_reference=approved.url, claims_json=claims,
            created_at=_now(), updated_at=_now(),
        )
        db.add(proposal)
        db.flush()
        approved.requirement_proposal_id = proposal.proposal_id
    approved.status = "researched"
    approved.version += 1
    approved.updated_at = _now()
    result = {
        "schema_version": "case-publisher-research-v1", "case_id": case.case_id,
        "candidate": {
            "candidate_id": approved.candidate_id, "candidate_version": approved.version,
            "url": approved.url, "domain": approved.domain, "title": approved.title,
            "status": approved.status, "authority_status": approved.authority_status,
            "approval_scope": approved.approval_scope,
            "publisher_ownership_status": "buyer_attested_not_independently_verified",
        },
        "research_status": "claims_pending_review" if claims else "zero_parser_yield",
        "evidence_outcome": "review_required" if claims else "unresolved",
        "claims": claims,
        "buyer_requirement_proposal": ({
            "case_id": case.case_id, "proposal_id": proposal.proposal_id,
            "proposal_version": proposal.version,
        } if proposal else None),
        "research": research,
        "provider_accounting": research.get("provider_accounting") or {
            "external_calls": 0, "paid_calls": 0,
        },
        "qualification_authority": "none", "cart_mutation": "not_authorized",
        "supplier_send": "not_authorized", "trace_id": case.case_id.removeprefix("sc-"),
    }
    json.dumps(result, sort_keys=True)
    approved.research_result_json = result
    db.commit()
    return result, None


__all__ = [
    "CASE_ALLOWED_CLAIM_TYPES", "approve_case_candidate", "candidate_id",
    "case_review_claims", "case_source_policy", "execute_case_candidate_research",
    "persist_discovered_candidates",
]
