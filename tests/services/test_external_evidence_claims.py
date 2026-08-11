from datetime import datetime, timedelta, timezone

from src.app.services.external_evidence_claims import accept_provider_claim_candidates


def _policy():
    return {
        "policy_version": "semantic-source-v1",
        "review_status": "approved",
        "reviewer_type": "independent_human",
        "reviewed_by": "tenant-source-owner",
        "licence": "tenant-authorized",
        "trust_tier": "authoritative",
        "allowed_claim_types": ["minimum_requirements"],
        "freshness_status": "fresh",
    }


def _item(value=32, **overrides):
    item = {
        "provider_id": "official-provider",
        "provider_authority": "official_source_index",
        "provider_capabilities": ["official_requirements"],
        "provider_source_policy": _policy(),
        "claim_candidates": [{
            "need_id": "minimum-memory",
            "claim_type": "minimum_requirements",
            "claim": "The official requirements specify at least 32 GB RAM.",
            "source_record_id": "requirements-2026:ram",
            "source_revision": "2026.08",
            "observed_at": "2026-08-06T00:00:00Z",
            "citation_id": "cite:requirements-2026:ram",
            "confidence": 0.94,
            "attribute_key": "ram_gb",
            "operator": ">=",
            "value": value,
            "unit": "GB",
        }],
    }
    item.update(overrides)
    return item


def test_enrolled_official_claim_becomes_accepted_evidence():
    result = accept_provider_claim_candidates(
        [_item()], concept="unfamiliar simulation workload",
    )

    assert result["status"] == "resolved"
    assert result["claims"][0]["status"] == "accepted"
    assert result["claims"][0]["authority"] == "official_requirements"
    assert result["normalized_evidence"][0]["status"] == "resolved"
    assert result["rejections"] == []


def test_missing_enrollment_policy_cannot_authorize_claim():
    result = accept_provider_claim_candidates(
        [_item(provider_source_policy=None)], concept="unfamiliar simulation workload",
    )

    assert result["status"] == "insufficient"
    assert result["claims"] == []
    assert result["rejections"][0]["reason"] == "source_policy_not_approved"


def test_registry_freshness_sla_is_evaluated_from_observed_at():
    item = _item()
    item["provider_source_policy"].update({
        "freshness_status": "not_yet_observed",
        "freshness_sla_hours": 24,
        "publisher_policy_id": "publisher-policy-v1",
    })
    item["claim_candidates"][0]["observed_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()

    fresh = accept_provider_claim_candidates([item], concept="simulation workload")
    assert fresh["status"] == "resolved"
    assert fresh["normalized_evidence"][0]["source_policy"]["freshness_status"] == "fresh"

    item["claim_candidates"][0]["observed_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=48)
    ).isoformat()
    stale = accept_provider_claim_candidates([item], concept="simulation workload")
    assert stale["status"] == "insufficient"
    assert stale["rejections"][0]["reason"] == "source_policy_not_approved"


def test_conflicting_provider_claims_block_the_requirement_set():
    second = _item(64)
    second["provider_id"] = "other-official-provider"
    second["claim_candidates"][0]["source_record_id"] = "requirements-other:ram"
    second["claim_candidates"][0]["citation_id"] = "cite:requirements-other:ram"

    result = accept_provider_claim_candidates(
        [_item(32), second], concept="unfamiliar simulation workload",
    )

    assert result["status"] == "conflicting"
    assert result["claims"] == []
    assert result["normalized_evidence"][0]["status"] == "contradictory"
    assert {row["reason"] for row in result["rejections"]} == {"claim_conflict"}
