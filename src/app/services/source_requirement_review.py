"""Create buyer-review proposals from policy-pending official-source claims."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.app.models.orm import RequirementProposal


def create_source_review_proposal(
    db: Any,
    *,
    provisional_claims: Sequence[Mapping[str, Any]],
    source_id: str,
    case_id: str,
    tenant_id: str,
    uid: str,
    source_policy_review: Mapping[str, Any] | None = None,
    research_lineage: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], RequirementProposal | None]:
    if not provisional_claims:
        return [], None
    source_reference = f"official-source:{source_id}"
    claims: list[dict[str, Any]] = []
    for raw_claim in provisional_claims:
        claim = dict(raw_claim)
        claim.update({
            "subject": "buyer_workload_requirement",
            "constraint_tier": "preferred",
            "source_reference": source_reference,
            "source_excerpt": str(
                claim.get("quoted_evidence_span") or claim.get("statement") or ""
            )[:500],
            "evidence_class": "official_policy_pending_source",
            "extraction_confidence": 1.0,
            "acceptance_status": "pending_buyer_review",
            "source_policy_review": {
                "status": str((source_policy_review or {}).get("status") or "not_recorded"),
                "reviewer": str((source_policy_review or {}).get("reviewer") or "not_recorded"),
                "reviewed_at": (source_policy_review or {}).get("reviewed_at"),
                "authority_effect": "held_until_independent_human_signoff",
            },
            "research_lineage": dict(research_lineage or {}),
        })
        claims.append(claim)
    now = datetime.now(timezone.utc)
    proposal = RequirementProposal(
        proposal_id=f"rp-{uuid.uuid4().hex[:20]}",
        case_id=case_id,
        tenant_id=tenant_id,
        uid=uid,
        version=1,
        status="pending_review",
        source_reference=source_reference,
        claims_json=claims,
        created_at=now,
        updated_at=now,
    )
    db.add(proposal)
    db.flush()
    return claims, proposal
