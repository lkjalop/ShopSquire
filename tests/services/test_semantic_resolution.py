from types import SimpleNamespace

import pytest

from src.app.services.semantic_resolution import (
    align_catalog,
    normalize_concept_evidence,
    reduce_semantic_proposal,
    validate_semantic_proposal,
)


def test_residual_route_asks_for_buyer_specific_material_details():
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
def test_unresolved_material_concept_clarifies_without_domain_rules(query, concept):
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

    assert decision.outcome == "clarify"
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
