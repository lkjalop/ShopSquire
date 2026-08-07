from types import SimpleNamespace

import pytest

from src.app.services.semantic_resolution import (
    ConceptEvidence,
    WorkloadHypothesis,
    compare_workload_hypotheses,
    align_catalog,
    fallback_semantic_proposal,
    normalize_concept_evidence,
    reduce_semantic_proposal,
    validate_semantic_proposal,
    validate_semantic_source_policy,
)


def test_hypothesis_comparison_uses_only_verified_typed_claim_coverage():
    hypotheses = [
        WorkloadHypothesis(
            hypothesis_id="local-workstation",
            label="Local workstation",
            required_claim_types=["recommended_requirements", "compatibility"],
            discriminating_unknown_ids=["execution-location"],
        ),
        WorkloadHypothesis(
            hypothesis_id="remote-client",
            label="Remote client",
            required_claim_types=["certification"],
            discriminating_unknown_ids=["execution-location"],
        ),
    ]
    evidence = [
        ConceptEvidence(
            concept="specialized workflow",
            status="resolved",
            claim="Official recommended requirements",
            claim_status="verified",
            claim_type="recommended_requirements",
        ),
        ConceptEvidence(
            concept="specialized workflow",
            status="insufficient",
            claim="Unverified compatibility assertion",
            claim_status="unverified",
            claim_type="compatibility",
        ),
    ]

    compared = compare_workload_hypotheses(hypotheses, evidence)

    assert compared[0]["evidence_coverage"] == "partial"
    assert compared[0]["matched_claim_types"] == ["recommended_requirements"]
    assert compared[0]["missing_claim_types"] == ["compatibility"]
    assert compared[0]["authority"] == "proposed"
    assert compared[1]["evidence_coverage"] == "unresolved"


def test_hypothesis_must_reference_a_declared_material_unknown():
    result = validate_semantic_proposal(
        {
            "desired_outcome": "qualify a product",
            "concepts": [{
                "text": "specialized workflow",
                "query_span": "specialized workflow",
                "status": "unresolved",
            }],
            "workload_hypotheses": [{
                "hypothesis_id": "local",
                "label": "Local execution",
                "discriminating_unknown_ids": ["missing-unknown"],
            }],
            "proposed_action": "research_then_clarify",
        },
        query="Find hardware for a specialized workflow",
    )

    assert result.outcome == "rejected"
    assert result.reasons == ("hypothesis_unknown_reference_invalid",)



def test_deterministic_relation_fallback_is_low_confidence_and_identified():
    proposal = fallback_semantic_proposal(
        query="Recommend a laptop capable of an unfamiliar simulation workflow.",
    )

    assert proposal["proposal_origin"] == "deterministic_fallback"
    assert proposal["confidence"] < 0.5
    assert proposal["proposed_action"] == "research_then_clarify"
    assert proposal["workload_hypotheses"] == []
    assert proposal["material_unknowns"][0]["resolution_source"] == "research"


def test_model_can_propose_competing_open_world_hypotheses_without_authorizing_one():
    result = validate_semantic_proposal(
        {
            "desired_outcome": "run a maintenance digital-twin workload",
            "product_category_candidates": [
                {"label": "portable computer", "confidence": 0.72},
                {"label": "mobile workstation", "confidence": 0.66},
            ],
            "concepts": [
                {
                    "text": "digital twin",
                    "query_span": "digital twin",
                    "status": "ambiguous",
                    "material": True,
                }
            ],
            "workload_hypotheses": [
                {
                    "hypothesis_id": "physical-process-simulation",
                    "label": "physical or process simulation",
                    "evidence_needed": ["simulation software", "model scale"],
                    "confidence": 0.54,
                },
                {
                    "hypothesis_id": "security-range-simulation",
                    "label": "security range simulation",
                    "evidence_needed": ["guest count", "virtualization platform"],
                    "confidence": 0.41,
                },
                {
                    "hypothesis_id": "remote-simulation-client",
                    "label": "remote simulation client",
                    "evidence_needed": ["execution location", "visualization target"],
                    "confidence": 0.38,
                },
            ],
            "material_unknowns": [
                {
                    "unknown_id": "workload-definition",
                    "description": "Which workload interpretation applies",
                    "resolution_source": "research",
                },
                {
                    "unknown_id": "execution-location",
                    "description": "Whether execution is local, remote, or hybrid",
                    "resolution_source": "buyer",
                },
            ],
            "evidence_questions": [],
            "proposed_action": "research_then_clarify",
            "confidence": 0.61,
        },
        query="Recommend a laptop for a digital twin used in machine maintenance",
    )

    assert result.outcome == "valid"
    assert result.proposal is not None
    assert len(result.proposal.workload_hypotheses) == 3
    assert {item.resolution_source for item in result.proposal.material_unknowns} == {
        "buyer",
        "research",
    }
    assert all(item.authority == "proposed" for item in result.proposal.workload_hypotheses)
    assert result.proposal.proposed_action == "research_then_clarify"

    reduced = reduce_semantic_proposal(result)
    assert reduced.catalog_authority == "blocked"
    assert reduced.product_category_candidates[0]["authority"] == "proposed"
    assert reduced.workload_hypotheses[0]["authority"] == "proposed"
    assert reduced.material_unknowns[1]["resolution_source"] == "buyer"
    assert reduced.interpretation_confidence == pytest.approx(0.61)


def test_open_world_hypotheses_are_bounded_and_cannot_claim_accepted_evidence():
    result = validate_semantic_proposal(
        {
            "desired_outcome": "support an unfamiliar analysis workflow",
            "concepts": [
                {
                    "text": "quantum lattice analysis",
                    "query_span": "quantum lattice analysis",
                    "status": "unresolved",
                }
            ],
            "workload_hypotheses": [
                {
                    "hypothesis_id": "candidate-one",
                    "label": "candidate interpretation",
                    "authority": "accepted",
                    "evidence_needed": ["official requirements"],
                    "confidence": 0.5,
                }
            ],
            "material_unknowns": [],
            "evidence_questions": [],
            "proposed_action": "research",
            "confidence": 0.5,
        },
        query="a computer for quantum lattice analysis",
    )

    assert result.outcome == "rejected"
    assert result.reasons == ("proposal_schema_invalid",)


def test_research_then_clarify_runs_research_before_asking_buyer_details():
    proposal = validate_semantic_proposal(
        {
            "desired_outcome": "run a digital-twin simulation",
            "concepts": [{"text": "digital twin", "status": "unresolved", "material": True}],
            "evidence_questions": [{
                "question_id": "software",
                "question": "Which software and version will run?",
                "purpose": "resolve_compatibility",
                "material": True,
            }],
            "proposed_action": "research_then_clarify",
            "confidence": 0.8,
        },
        query="a laptop for a digital twin",
    )

    decision = reduce_semantic_proposal(proposal)

    assert decision.outcome == "research"
    assert decision.residual_route == "SEARCH"
    assert decision.next_permitted_action == "run_bounded_concept_research"


def test_research_discovered_ambiguity_blocks_catalog_and_asks_buyer():
    validation = validate_semantic_proposal(
        {
            "desired_outcome": "run an unfamiliar simulation",
            "concepts": [{"text": "adaptive simulation", "status": "unresolved", "material": True}],
            "workload_hypotheses": [
                {
                    "hypothesis_id": "local",
                    "label": "Local execution",
                    "required_claim_types": ["recommended_requirements"],
                    "discriminating_unknown_ids": ["deployment"],
                },
                {
                    "hypothesis_id": "remote",
                    "label": "Remote execution",
                    "required_claim_types": ["compatibility"],
                    "discriminating_unknown_ids": ["deployment"],
                },
            ],
            "material_unknowns": [{
                "unknown_id": "deployment",
                "description": "Where execution occurs",
                "resolution_source": "buyer",
            }],
            "evidence_questions": [{
                "question_id": "deployment",
                "question": "Will this run locally, remotely, or in a hybrid setup?",
                "purpose": "resolve_compatibility",
                "resolves_unknown_ids": ["deployment"],
                "decision_impacts": ["architecture", "product_set"],
            }],
            "proposed_action": "research_then_clarify",
        },
        query="hardware for an adaptive simulation",
    )
    evidence = [
        ConceptEvidence(
            concept="adaptive simulation", status="resolved", claim="requirements",
            claim_status="verified", claim_type="recommended_requirements",
        ),
        ConceptEvidence(
            concept="adaptive simulation", status="resolved", claim="compatibility",
            claim_status="verified", claim_type="compatibility",
        ),
    ]

    decision = reduce_semantic_proposal(
        validation, evidence=evidence, research_attempted=True, research_status="resolved",
    )

    assert decision.outcome == "clarify"
    assert decision.catalog_authority == "blocked"
    assert decision.reasons == ("research_discovered_material_ambiguity",)
    assert decision.next_permitted_action == "ask_high_value_disambiguation"


def test_research_then_clarify_asks_only_after_bounded_research_is_insufficient():
    proposal = validate_semantic_proposal(
        {
            "desired_outcome": "run a digital-twin simulation",
            "concepts": [{"text": "digital twin", "status": "unresolved", "material": True}],
            "evidence_questions": [{
                "question_id": "software",
                "question": "Which software and version will run?",
                "purpose": "resolve_compatibility",
                "material": True,
            }],
            "proposed_action": "research_then_clarify",
            "confidence": 0.8,
        },
        query="a laptop for a digital twin",
    )

    decision = reduce_semantic_proposal(
        proposal,
        research_attempted=True,
        research_status="insufficient",
    )

    assert decision.outcome == "clarify"
    assert decision.residual_route == "ASK"
    assert "material_buyer_input_required" in decision.residual_reasons


def test_residual_route_searches_only_when_public_evidence_is_missing():
    proposal = validate_semantic_proposal(
        {
            "desired_outcome": "resolve iron birch material identity",
            "concepts": [{"text": "iron birch", "status": "unresolved", "material": True}],
            "evidence_questions": [],
            "proposed_action": "research",
            "confidence": 0.8,
        },
        query="chairs made from iron birch",
    )

    decision = reduce_semantic_proposal(proposal)

    assert decision.residual_route == "SEARCH"
    assert decision.next_permitted_action == "run_bounded_concept_research"


def test_residual_route_uses_connector_after_material_qualification():
    proposal = validate_semantic_proposal(
        {
            "desired_outcome": "find a known product",
            "concepts": [],
            "evidence_questions": [],
            "proposed_action": "search_catalog",
            "confidence": 0.9,
        },
        query="find a known product",
    )

    decision = reduce_semantic_proposal(proposal)

    assert decision.residual_route == "CONNECTOR"
    assert decision.catalog_authority == "permitted"


def test_authorize_route_is_a_next_step_not_an_authorization_grant():
    proposal = validate_semantic_proposal(
        {
            "desired_outcome": "commit the selected order",
            "concepts": [],
            "evidence_questions": [],
            "proposed_action": "search_catalog",
            "confidence": 0.9,
        },
        query="commit the selected order",
    )

    decision = reduce_semantic_proposal(proposal, authorization_requested=True)

    assert decision.residual_route == "AUTHORIZE"
    assert decision.catalog_authority == "permitted"
    assert decision.authorization_granted is False
    assert "consequential_action_requires_policy" in decision.residual_reasons


@pytest.mark.parametrize(
    ("query", "concept"),
    [
        ("30 laptops for digital twin simulations", "digital twin simulations"),
        ("a workstation for DNA sequencing analysis", "DNA sequencing analysis"),
        ("a computer for a quantum simulation", "quantum simulation"),
        ("20 iron birch chairs for a hotel", "iron birch"),
        ("a sassafras rocking chair", "sassafras"),
        ("a CPAP breathing machine", "CPAP breathing machine"),
    ],
)
def test_unresolved_material_concept_researches_without_domain_rules(query, concept):
    proposal = validate_semantic_proposal(
        {
            "desired_outcome": "find a suitable product",
            "concepts": [
                {
                    "text": concept,
                    "status": "unresolved",
                    "material": True,
                    "interpretations": ["meaning one", "meaning two"],
                }
            ],
            "evidence_questions": [
                {
                    "question_id": "scope",
                    "question": "Which exact standard, software, material, or use is required?",
                    "purpose": "resolve_concept",
                    "material": True,
                }
            ],
            "proposed_action": "research_then_clarify",
            "confidence": 0.8,
        },
        query=query,
    )

    decision = reduce_semantic_proposal(proposal, evidence=[])

    assert decision.outcome == "research"
    assert decision.catalog_authority == "blocked"
    assert "unresolved_material_concept" in decision.reasons
    assert "catalog_recommendation" in decision.state_prevented


def test_concept_must_be_anchored_in_buyer_text():
    decision = validate_semantic_proposal(
        {
            "desired_outcome": "find a chair",
            "concepts": [{"text": "mahogany", "status": "unresolved", "material": True}],
            "evidence_questions": [],
            "proposed_action": "research",
            "confidence": 0.9,
        },
        query="find an iron birch chair",
    )
    assert decision.outcome == "rejected"
    assert decision.reasons == ("concept_not_anchored_in_query",)


def test_advisory_normalization_is_allowed_only_with_buyer_anchored_span():
    decision = validate_semantic_proposal(
        {
            "desired_outcome": "find a suitable workstation",
            "concepts": [{
                "text": "maintenance digital twin",
                "query_span": "maintenance digital twin",
                "normalized_label": "predictive maintenance simulation",
                "status": "unresolved",
                "material": True,
            }],
            "evidence_questions": [],
            "proposed_action": "research",
            "confidence": 0.8,
        },
        query="a laptop for a maintenance digital twin",
    )

    assert decision.outcome == "valid"
    assert decision.proposal is not None
    assert decision.proposal.concepts[0].normalized_label == "predictive maintenance simulation"


def test_normalized_label_cannot_substitute_for_missing_query_anchor():
    decision = validate_semantic_proposal(
        {
            "desired_outcome": "find a suitable workstation",
            "concepts": [{
                "text": "maintenance digital twin",
                "query_span": "unmentioned secret workload",
                "normalized_label": "predictive maintenance simulation",
                "status": "unresolved",
                "material": True,
            }],
            "evidence_questions": [],
            "proposed_action": "research",
            "confidence": 0.8,
        },
        query="a laptop for a maintenance digital twin",
    )

    assert decision.outcome == "rejected"
    assert decision.reasons == ("concept_not_anchored_in_query",)


def test_resolved_evidence_allows_catalog_alignment_but_does_not_invent_fit():
    proposal = validate_semantic_proposal(
        {
            "desired_outcome": "find hotel chairs made from iron birch",
            "concepts": [{"text": "iron birch", "status": "unresolved", "material": True}],
            "evidence_questions": [],
            "proposed_action": "research",
            "confidence": 0.9,
        },
        query="find hotel chairs made from iron birch",
    )
    evidence = normalize_concept_evidence(
        [
            {
                "concept": "iron birch",
                "status": "resolved",
                "claim": "A supplier trade name requiring species confirmation.",
                "source_id": "approved-material-registry",
                "source_record_id": "material-42",
                "source_revision": "2026-08",
                "observed_at": "2026-08-05T00:00:00Z",
                "citation_id": "cite:v1:material-42",
                "claim_type": "material_identity",
                "source_policy": {
                    "policy_version": "semantic-source-v1",
                    "review_status": "approved",
                    "reviewer_type": "independent_human",
                    "reviewed_by": "procurement-librarian-1",
                    "licence": "tenant-authorized",
                    "trust_tier": "authoritative",
                    "allowed_claim_types": ["material_identity"],
                    "freshness_status": "fresh",
                },
            }
        ]
    )
    reduced = reduce_semantic_proposal(proposal, evidence=evidence)
    alignment = align_catalog(
        reduced,
        [
            {"sku": "CHAIR-ASH", "alignment_status": "alternative"},
            {"sku": "CHAIR-OAK", "alignment_status": "alternative"},
        ],
    )

    assert reduced.outcome == "proceed_catalog"
    assert alignment.status == "no_exact_catalog_match"
    assert alignment.exact == ()
    assert alignment.alternatives == ("CHAIR-ASH", "CHAIR-OAK")
    assert "supplier_enquiry_after_buyer_commitment" in alignment.permitted_actions


def test_simulation_contract_can_resolve_only_when_explicitly_enabled(monkeypatch):
    evidence_row = {
        "concept": "digital twin simulation",
        "status": "resolved",
        "claim": "A versioned demonstration contract defines the synthetic capability floor.",
        "source_id": "demo-contract",
        "source_record_id": "digital-twin-profile-1",
        "source_revision": "2026-08-05",
        "observed_at": "2026-08-05T00:00:00Z",
        "citation_id": "fixture:digital-twin-profile-1:2026-08-05",
        "claim_type": "minimum_requirements",
        "source_policy": {
            "policy_version": "semantic-source-v1",
            "review_status": "simulation_contract",
            "reviewer_type": "deterministic_fixture",
            "reviewed_by": "versioned-test-contract",
            "licence": "synthetic-demonstration-only",
            "trust_tier": "simulation",
            "allowed_claim_types": ["minimum_requirements"],
            "freshness_status": "fresh",
            "simulation_only": True,
        },
    }

    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.delenv("SEMANTIC_SIMULATION_AUTHORITY_ENABLED", raising=False)
    assert normalize_concept_evidence([evidence_row])[0].status == "insufficient"

    monkeypatch.setenv("SEMANTIC_SIMULATION_AUTHORITY_ENABLED", "1")
    accepted = normalize_concept_evidence([evidence_row])[0]
    assert accepted.status == "resolved"
    assert accepted.source_policy_status == "simulation_contract"


def test_simulation_contract_never_resolves_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SEMANTIC_SIMULATION_AUTHORITY_ENABLED", "1")
    allowed, reason = validate_semantic_source_policy(
        {
            "policy_version": "semantic-source-v1",
            "review_status": "simulation_contract",
            "reviewer_type": "deterministic_fixture",
            "reviewed_by": "versioned-test-contract",
            "licence": "synthetic-demonstration-only",
            "trust_tier": "simulation",
            "allowed_claim_types": ["minimum_requirements"],
            "freshness_status": "fresh",
            "simulation_only": True,
        },
        claim_type="minimum_requirements",
    )
    assert allowed is False
    assert reason == "simulation_contract_not_permitted"


def test_evidence_without_stable_provenance_is_not_resolved():
    evidence = normalize_concept_evidence(
        [{"concept": "iron birch", "status": "resolved", "claim": "trust me"}]
    )
    assert evidence[0].status == "insufficient"
    assert evidence[0].claim_status == "unverified"


def test_provenance_cannot_resolve_concept_without_independent_source_policy():
    evidence = normalize_concept_evidence([{
        "concept": "iron birch",
        "status": "resolved",
        "claim": "A material identity claim.",
        "claim_type": "material_identity",
        "source_id": "search-result",
        "source_record_id": "result-1",
        "source_revision": "v1",
        "observed_at": "2026-08-05T00:00:00Z",
        "citation_id": "cite:result-1",
        "source_policy": {
            "policy_version": "v1",
            "review_status": "approved",
            "reviewer_type": "automated",
            "reviewed_by": "codex",
            "licence": "unknown",
            "trust_tier": "unreviewed",
            "allowed_claim_types": ["material_identity"],
            "freshness_status": "fresh",
        },
    }])
    assert evidence[0].status == "insufficient"
    assert evidence[0].source_policy_status == "source_policy_not_independently_reviewed"


def test_evidence_orchestrator_selects_generic_concept_lane():
    from src.app.services.evidence_orchestrator import select_legs

    plan = SimpleNamespace(
        intent="product_search",
        needs_market_evidence=False,
        quantity=None,
        availability_horizon_days=None,
        category=None,
        needs_concept_resolution=True,
    )
    assert select_legs(plan, query="unknown product concept") == ["concept_resolution"]


def test_concept_lane_requires_explicit_external_research_consent(monkeypatch):
    from src.app.services.evidence_orchestrator import gather_evidence

    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("external provider must not run without consent")

    monkeypatch.setattr(
        "src.app.services.external_product_research_service.run_external_research_stage",
        forbidden,
    )
    plan = SimpleNamespace(
        intent="product_search",
        needs_market_evidence=False,
        quantity=None,
        availability_horizon_days=None,
        needs_concept_resolution=True,
        external_research_authorized=False,
        semantic_proposal={
            "concepts": [{"text": "iron birch", "material": True}],
        },
    )
    bundle = gather_evidence(plan, query="20 iron birch chairs", web_consent=False)

    assert called is False
    assert bundle["legs"]["concept_resolution"]["data"]["status"] == "consent_required"
