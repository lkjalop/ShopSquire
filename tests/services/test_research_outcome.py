from src.app.services.research_outcome import build_research_outcome


def test_held_claims_are_not_reported_as_no_evidence_or_verified() -> None:
    outcome = build_research_outcome(
        case_id="sc-rockwell",
        case_revision=4,
        operation_id="chat:idem-4",
        research={
            "source_resolution": {
                "source_intake_certificate": {
                    "schema_version": "buyer-source-intake-certificate-v1",
                    "resolution": {
                        "status": "resolved",
                        "selected_source_id": "rockwell_emulate3d_official_requirements",
                    },
                    "security": {"status": "observed_untrusted_content_pending_compilation"},
                    "execution": {"origin_fetch_status": "completed", "network_execution": True},
                    "claim_compilation": {
                        "status": "claims_pending_policy_review",
                        "accepted": 0,
                        "provisional": 9,
                        "rejected": 0,
                    },
                },
                "research": {
                    "evidence_outcome": "claims_pending_policy_review",
                    "next_action": "independent_policy_review",
                    "failures": [{"code": "independent_policy_human_signoff_pending"}],
                },
            },
        },
        requirements={"accepted": [], "rejected": [], "unresolved": []},
        catalog_authority="blocked",
        commerce_authority="none",
    )

    assert outcome.case_revision == 4
    assert outcome.fetch_status == "completed"
    assert outcome.parsed_claim_count == 9
    assert outcome.held_claim_count == 9
    assert outcome.accepted_claim_count == 0
    assert outcome.source_ownership_status == "observed_held"
    assert outcome.requirement_completeness == "partial"
    assert outcome.catalog_authority == "blocked"
    assert outcome.commerce_authority == "none"
    assert outcome.next_action == "independent_policy_review"
    assert outcome.failure_code == "independent_policy_human_signoff_pending"


def test_resolved_connector_identity_and_requirements_are_complete() -> None:
    outcome = build_research_outcome(
        case_id="sc-bg3",
        case_revision=2,
        operation_id="chat:bg3",
        research={
            "workload_authorization": {
                "status": "authorized",
                "evidence": [{
                    "provider_id": "steam",
                    "canonical_title": "Baldur's Gate 3",
                    "publisher": "Larian Studios",
                    "app_id": "1086940",
                    "release_state": "released",
                    "release_date": "2023-08-03",
                    "requirements_completeness": "minimum_and_recommended",
                    "compiled_requirements": [
                        {"attribute": "ram_gb", "status": "accepted"},
                        {"attribute": "gpu_vram_gb", "status": "accepted"},
                    ],
                }],
            },
        },
        requirements={"accepted": [{"attribute": "ram_gb"}], "rejected": [], "unresolved": []},
        catalog_authority="permitted",
        commerce_authority="none",
    )

    assert outcome.identity is not None
    assert outcome.identity.title == "Baldur's Gate 3"
    assert outcome.identity.app_id == "1086940"
    assert outcome.accepted_claim_count >= 1
    assert outcome.requirement_completeness == "complete"
    assert outcome.catalog_authority == "permitted"
