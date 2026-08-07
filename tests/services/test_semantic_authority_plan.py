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


def test_research_consent_sentence_is_not_a_new_workload_concept():
    proposal = _coverage(
        "Use the prior workload. I consent to that research using approved official sources."
    )

    concepts = [str(item.get("text") or "") for item in proposal.get("concepts") or []]
    assert not any("research" in item.lower() for item in concepts)
    assert not any("official sources" in item.lower() for item in concepts)
