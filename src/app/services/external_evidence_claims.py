"""Validate typed provider claims before they enter recommendation requirements.

Search text is never parsed here. Enrolled connectors must return bounded atomic
claims with stable provenance; source policy and provider authority are supplied by
the registry, not by fetched content.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable

from src.app.services.semantic_resolution import validate_semantic_source_policy


_AUTHORITY = {
    ("official_source_index", "official_requirements"): "official_requirements",
    ("tenant_approved_repository", "approved_tenant_document"):
        "approved_tenant_document",
}


def accept_provider_claim_candidates(
    items: Iterable[dict[str, Any]], *, concept: str,
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    normalized: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in list(items)[:8]:
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("provider_id") or "").strip()[:160]
        provider_authority = str(item.get("provider_authority") or "").strip()
        capabilities = {
            str(value).strip() for value in item.get("provider_capabilities") or []
        }
        policy = item.get("provider_source_policy")
        for index, candidate in enumerate(list(item.get("claim_candidates") or [])[:16]):
            if not isinstance(candidate, dict):
                continue
            claim_id = str(candidate.get("source_record_id") or f"claim-{index}")[:240]
            claim_type = str(candidate.get("claim_type") or "").strip()
            policy_ok, _policy_reason = validate_semantic_source_policy(
                policy, claim_type=claim_type,
            )
            if not policy_ok:
                rejected.append({"claim_id": claim_id, "reason": "source_policy_not_approved"})
                continue
            compiler_authority = next(
                (
                    value for (authority, capability), value in _AUTHORITY.items()
                    if authority == provider_authority and capability in capabilities
                ),
                None,
            )
            if compiler_authority is None:
                rejected.append({"claim_id": claim_id, "reason": "provider_not_authoritative"})
                continue
            required = (
                provider_id,
                claim_id,
                str(candidate.get("source_revision") or "").strip(),
                str(candidate.get("observed_at") or "").strip(),
                str(candidate.get("citation_id") or "").strip(),
                str(candidate.get("claim") or "").strip(),
            )
            if not all(required):
                rejected.append({"claim_id": claim_id, "reason": "provenance_incomplete"})
                continue
            row = {
                "need_id": str(candidate.get("need_id") or claim_id)[:64],
                "subject_span": str(concept or "")[:120],
                "claim_type": claim_type,
                "status": "accepted",
                "source_id": provider_id,
                "source_record_id": claim_id,
                "observed_at": str(candidate.get("observed_at"))[:80],
                "confidence": candidate.get("confidence"),
                "attribute_key": str(candidate.get("attribute_key") or "")[:80],
                "operator": str(candidate.get("operator") or "")[:12],
                "value": candidate.get("value"),
                "unit": str(candidate.get("unit") or "")[:40] or None,
                "authority": compiler_authority,
                "lineage_root": provider_id,
            }
            accepted.append(row)
            normalized.append({
                "concept": str(concept or "")[:120],
                "status": "resolved",
                "claim": str(candidate.get("claim"))[:500],
                "claim_type": claim_type,
                "source_id": provider_id,
                "source_record_id": claim_id,
                "source_revision": str(candidate.get("source_revision"))[:120],
                "observed_at": str(candidate.get("observed_at"))[:80],
                "citation_id": str(candidate.get("citation_id"))[:200],
                "source_policy": dict(policy),
            })

    grouped: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    for index, claim in enumerate(accepted):
        signature = json.dumps(
            [claim.get("operator"), claim.get("value"), claim.get("unit")],
            sort_keys=True,
            default=str,
        )
        grouped[(str(claim.get("claim_type")), str(claim.get("attribute_key")))].append(
            (index, signature)
        )
    conflicting_indexes: set[int] = set()
    for rows in grouped.values():
        if len({signature for _, signature in rows}) > 1:
            conflicting_indexes.update(index for index, _ in rows)
    if conflicting_indexes:
        conflict_claims = [accepted[index] for index in sorted(conflicting_indexes)]
        for claim in conflict_claims:
            rejected.append({
                "claim_id": claim["source_record_id"],
                "reason": "claim_conflict",
            })
        accepted = [
            claim for index, claim in enumerate(accepted)
            if index not in conflicting_indexes
        ]
        normalized = [
            row for index, row in enumerate(normalized)
            if index not in conflicting_indexes
        ]
        first = conflict_claims[0]
        normalized.append({
            "concept": str(concept or "")[:120],
            "status": "contradictory",
            "claim": "Enrolled sources returned conflicting requirement values.",
            "claim_type": first.get("claim_type"),
            "source_id": "conflict-detector",
            "source_record_id": "conflict:" + str(first.get("attribute_key")),
            "source_revision": "runtime",
            "observed_at": first.get("observed_at"),
            "citation_id": "conflict:" + str(first.get("attribute_key")),
            "source_policy": {
                "policy_version": "semantic-source-v1",
                "review_status": "rejected",
            },
        })
        status = "conflicting"
    else:
        status = "resolved" if accepted else "insufficient"
    return {
        "status": status,
        "claims": accepted,
        "normalized_evidence": normalized,
        "rejections": rejected,
    }
