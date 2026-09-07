from src.app.services.research_outcome import build_research_outcome


def test_complete_publisher_document_does_not_hide_partial_claim_compilation():
    outcome = build_research_outcome(case_id="sc-partial", case_revision=2,
        operation_id="op-partial", catalog_authority="permitted", commerce_authority="none",
        research={"workload_authorization": {"evidence": [{
            "requirements_completeness": "minimum_and_recommended",
            "compiled_requirements": [{"attribute_key": "ram_gb", "value": 8}],
            "claim_rejections": [{"attribute_key": "storage_gb", "reason": "attribute_not_registry_authorized"}],
        }]}}, requirements={"accepted": [{"claim_id": "ram-1"}]})
    assert outcome.requirement_completeness == "partial"


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


def test_top_level_held_ledger_rows_are_counted() -> None:
    outcome = build_research_outcome(
        case_id="sc-agisoft", case_revision=3, operation_id="chat:agisoft",
        research={"status": "requirements_resolved"},
        requirements={
            "held": [
                {"claim_id": "c1", "authority_status": "observed_held"},
                {"claim_id": "c2", "authority_status": "pending_independent_policy_review"},
            ],
            "accepted": [], "rejected": [],
        },
        catalog_authority="provisional", commerce_authority="none",
    )

    assert outcome.parsed_claim_count == 2
    assert outcome.held_claim_count == 2
    assert outcome.source_ownership_status == "observed_held"


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


def test_cited_identity_precedes_untrusted_candidate_page_title() -> None:
    outcome = build_research_outcome(
        case_id="sc-unseen",
        case_revision=2,
        operation_id="chat:unseen",
        research={
            "candidates": [{
                "candidate_id": "candidate-1",
                "title": "Where Winds Meet System Requirements: Can You Run It?",
            }],
            "identity_resolution": {
                "status": "resolved",
                "authority": "cited_candidate_rows_only",
                "identity": {
                    "canonical_title": "Where Winds Meet",
                    "publisher": None,
                    "publisher_domain": None,
                    "release_state": "unknown",
                    "supporting_row_ids": ["candidate-1"],
                },
            },
        },
        requirements={"accepted": [], "rejected": []},
        catalog_authority="blocked",
        commerce_authority="none",
    )

    assert outcome.identity is not None
    assert outcome.identity.title == "Where Winds Meet"
    assert outcome.requirement_completeness == "identity_only"


def test_structured_provider_enriches_earlier_identity_resolution_projection() -> None:
    outcome = build_research_outcome(
        case_id="sc-rotating", case_revision=2, operation_id="chat:rotating",
        research={
            "identity_resolution": {
                "status": "resolved", "authority": "cited_candidate_rows_only",
                "identity": {
                    "canonical_title": "Powers Downtown", "publisher": None,
                    "release_state": "unknown", "supporting_row_ids": ["candidate-6"],
                },
            },
            "structured_provider_resolution": {
                "status": "resolved", "evidence": [{
                    "status": "resolved", "provider_id": "steam",
                    "canonical_title": "Powers Downtown", "publisher": "Masaharu Studio",
                    "app_id": "4070390", "release_state": "unreleased",
                    "release_date": "2 Sep, 2026", "source_url": "https://store.steampowered.com/app/4070390/",
                    "requirements_completeness": "minimum_only",
                    "compiled_requirements": [{"attribute_key": "ram_gb"}],
                }],
            },
        },
        requirements={"accepted": [], "rejected": []},
        catalog_authority="permitted", commerce_authority="none",
    )

    assert outcome.identity is not None
    assert outcome.identity.model_dump() == {
        "title": "Powers Downtown", "publisher": "Masaharu Studio",
        "app_id": "4070390", "release_state": "unreleased",
        "release_date": "2 Sep, 2026",
    }


def test_failed_identity_attempt_does_not_promote_candidate_page_title() -> None:
    outcome = build_research_outcome(
        case_id="sc-cupix",
        case_revision=2,
        operation_id="chat:cupix",
        research={
            "candidates": [{
                "candidate_id": "candidate-1",
                "title": "Unrelated Game System Requirements",
            }],
            "identity_resolution": {
                "status": "unresolved",
                "identity": None,
                "model_calls": 2,
                "authority": "none",
                "failure_code": "identity_model_output_invalid",
            },
        },
        requirements={"accepted": [], "rejected": []},
        catalog_authority="blocked",
        commerce_authority="none",
    )

    assert outcome.identity is None
    assert outcome.requirement_completeness == "none"


def test_revision_bound_identity_projection_precedes_candidate_title() -> None:
    outcome = build_research_outcome(
        case_id="sc-cupix",
        case_revision=2,
        operation_id="chat:cupix",
        research={
            "ambiguity_exploration": {
                "publisher_candidates": [{
                    "candidate_id": "candidate-1",
                    "title": "Contact CupixWorks Support - Support Center",
                }],
            },
            "workload_authorization": {
                "status": "blocked",
                "evidence": [{
                    "status": "identity_resolved_requirements_pending",
                    "canonical_title": "CupixWorks",
                    "release_state": "unknown",
                }],
            },
        },
        requirements={"accepted": [], "rejected": []},
        catalog_authority="blocked",
        commerce_authority="none",
    )

    assert outcome.identity is not None
    assert outcome.identity.title == "CupixWorks"


def test_authoritative_structured_evidence_wins_over_degraded_discovery_diagnostics() -> None:
    outcome = build_research_outcome(
        case_id="sc-mio",
        case_revision=2,
        operation_id="chat:mio",
        research={
            "provider_status": "degraded",
            "receipts": [{"provider_status": "timeout"}],
            "structured_provider_resolution": {
                "status": "resolved",
                "evidence": [{
                    "status": "resolved",
                    "provider_id": "steam",
                    "canonical_title": "MIO: Memories in Orbit",
                    "app_id": "1672810",
                    "release_state": "released",
                    "release_date": "20 Jan, 2026",
                    "requirements_completeness": "minimum_and_recommended",
                    "compiled_requirements": [
                        {"attribute_key": "ram_gb", "operator": ">=", "value": 8},
                        {"attribute_key": "gpu_vram_gb", "operator": ">=", "value": 4},
                    ],
                }],
            },
        },
        requirements={"accepted": [], "rejected": []},
        catalog_authority="permitted",
        commerce_authority="none",
    )

    assert outcome.discovery_status == "completed"
    assert outcome.fetch_status == "completed"
    assert outcome.identity is not None
    assert outcome.identity.title == "MIO: Memories in Orbit"
    assert outcome.requirement_completeness == "complete"
    assert outcome.accepted_claim_count == 2


def test_identity_confirmation_failure_outranks_lower_ladder_rejections() -> None:
    outcome = build_research_outcome(
        case_id="sc-confirm", case_revision=2, operation_id="chat:confirm",
        research={
            "evidence_ladder": [{"rejection_reason": "publisher_not_yet_accepted"}],
            "identity_resolution": {
                "status": "confirmation_required",
                "failure_code": "low_confidence_identity_confirmation_required",
                "identity": {"canonical_title": "The Blood of Dawnwalker"},
                "cited_rows": [{"row_id": "candidate-1"}],
                "model_calls": 1,
                "authority": "cited_candidate_rows_only",
            },
        },
        requirements={"accepted": [], "rejected": []},
        catalog_authority="blocked", commerce_authority="none",
    )

    assert outcome.identity.title == "The Blood of Dawnwalker"
    assert outcome.failure_code == "low_confidence_identity_confirmation_required"
    assert outcome.next_action == "confirm_canonical_identity"
