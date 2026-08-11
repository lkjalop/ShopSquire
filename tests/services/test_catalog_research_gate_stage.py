from src.app.services.recommendation_core.catalog_research_gate_stage import (
    CatalogResearchGateInput,
    run_catalog_research_gate,
)


def test_category_similarity_and_unresolved_certification_require_research():
    output = run_catalog_research_gate(CatalogResearchGateInput(
        query="Only officially supported hardware is acceptable",
        retrieval_count=10, returned_product_count=10,
        normalized_requirement_count=0, qualified_product_count=0,
        unknown_requirement_count=20, possible_requirement_count=30,
    ))
    assert output.adjudication.research_needed is True
    assert output.adjudication.qualification_authority == "none"
    assert "category_similarity_only" in output.adjudication.reason_codes
    assert "explicit_constraints_unresolved" in output.adjudication.reason_codes


def test_positive_evidence_can_authorize_qualification_without_research():
    output = run_catalog_research_gate(CatalogResearchGateInput(
        query="Find a suitable laptop", retrieval_count=3, returned_product_count=3,
        normalized_requirement_count=4, qualified_product_count=3,
        unknown_requirement_count=0, possible_requirement_count=12,
    ))
    assert output.adjudication.research_needed is False
    assert output.adjudication.qualification_authority == "positive_evidence"
