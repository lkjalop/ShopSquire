from src.app.services.recommendation_core.plan import derive_plan
from src.app.services.recommendation_core.semantic_coverage import (
    unresolved_purpose_proposal,
)
from src.app.services.recommendation_core.turn_router import TurnDecision


def _coverage(query: str) -> dict:
    return unresolved_purpose_proposal(
        query=query,
        node_path="Electronics > Computers > Laptops",
        existing_semantic={},
    )


def test_product_category_does_not_authorize_an_uninterpreted_material_purpose():
    coverage = _coverage(
        "I need a laptop for digital twin simulation of a cyber attack"
    )
    decision = TurnDecision(
        lane="SEARCH",
        node_handle="el-6-3-1",
        semantic_proposal={"validation": "rejected", "reason": "empty_model_output"},
        coverage_abstention_shadow=coverage,
    )

    plan = derive_plan(decision)

    assert plan.semantic_authority_state == "uninterpreted_material"
    assert plan.needs_concept_resolution is True
    assert plan.semantic_proposal["proposal_origin"] == "coverage_abstention"


def test_model_guessed_use_case_and_requirements_do_not_override_coverage_abstention():
    decision = TurnDecision(
        lane="SEARCH",
        node_handle="el-6-6",
        requirements={"ram_gb": ((">=", 16.0),)},
        use_cases=("engineering_student",),
        semantic_proposal={},
        coverage_abstention_shadow=_coverage(
            "I need a laptop for digital twin simulation of a cyber attack"
        ),
    )

    plan = derive_plan(decision)

    assert plan.semantic_authority_state == "uninterpreted_material"
    assert plan.needs_concept_resolution is True


def test_model_guessed_run_on_relationship_does_not_create_semantic_authority():
    decision = TurnDecision(
        lane="SEARCH",
        node_handle="el-6-11-2",
        relationship="run_on",
        semantic_proposal={},
        coverage_abstention_shadow=_coverage(
            "I need something for digital twin simulation of a cyber attack"
        ),
    )

    plan = derive_plan(decision)

    assert plan.semantic_authority_state == "uninterpreted_material"
    assert plan.needs_concept_resolution is True


def test_model_guessed_workload_entity_does_not_create_semantic_authority():
    decision = TurnDecision(
        lane="SEARCH",
        node_handle="el-6-11-2",
        workload_entities=(("software", "cybersecurity simulation"),),
        semantic_proposal={},
        coverage_abstention_shadow=_coverage(
            "I need something for digital twin simulation of a cyber attack"
        ),
    )

    plan = derive_plan(decision)

    assert plan.semantic_authority_state == "uninterpreted_material"
    assert plan.needs_concept_resolution is True


def test_audience_only_context_does_not_become_a_workload_abstention():
    decision = TurnDecision(
        lane="SEARCH",
        node_handle="el-6-6",
        audience_contexts=("family_member",),
        semantic_proposal={},
        coverage_abstention_shadow=_coverage("I need a laptop for my daughter"),
    )

    plan = derive_plan(decision)

    assert plan.semantic_authority_state == "not_material"
    assert plan.needs_concept_resolution is False


def test_same_material_purpose_has_same_authority_with_or_without_product_noun():
    with_product = _coverage(
        "I need a laptop for digital twin simulation of a cyber attack"
    )
    without_product = _coverage(
        "I need something for digital twin simulation of a cyber attack"
    )

    with_plan = derive_plan(TurnDecision(
        semantic_proposal={}, coverage_abstention_shadow=with_product,
    ))
    without_plan = derive_plan(TurnDecision(
        semantic_proposal={}, coverage_abstention_shadow=without_product,
    ))

    assert with_plan.semantic_authority_state == without_plan.semantic_authority_state
    assert with_plan.needs_concept_resolution is True
    assert without_plan.needs_concept_resolution is True


def test_ordinary_catalog_request_does_not_over_abstain():
    decision = TurnDecision(
        lane="SEARCH",
        node_handle="el-6-3-1",
        semantic_proposal={},
        coverage_abstention_shadow=_coverage("show me laptops under $1000"),
    )

    plan = derive_plan(decision)

    assert plan.semantic_authority_state == "not_material"
    assert plan.needs_concept_resolution is False


def test_known_workload_with_performance_modifier_does_not_over_abstain():
    coverage = _coverage("i want to play valorant at 144fps")

    assert coverage == {}


def test_known_use_case_and_product_category_combine_for_coverage():
    coverage = _coverage("is $1800 enough for a gaming laptop?")

    assert coverage == {}


def test_common_university_assignments_and_video_calls_remain_covered():
    coverage = _coverage(
        "I need a portable laptop for university assignments and video calls under $1800."
    )

    assert coverage == {}


def test_fictional_technical_workload_still_fails_closed_after_coverage_extension():
    coverage = _coverage(
        "I need a mobile workstation for the fictional GeoStrata Coupled Solver X."
    )

    assert coverage["validation"] == "valid"
    assert coverage["concepts"][0]["status"] == "unresolved"


def test_research_consent_sentence_is_not_a_new_workload_concept():
    proposal = _coverage(
        "Use the prior workload. I consent to that research using approved official sources."
    )

    concepts = [str(item.get("text") or "") for item in proposal.get("concepts") or []]
    assert not any("research" in item.lower() for item in concepts)
    assert not any("official sources" in item.lower() for item in concepts)
