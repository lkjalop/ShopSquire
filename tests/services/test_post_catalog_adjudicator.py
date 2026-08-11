from src.app.services.recommendation_core.post_catalog_adjudicator import (
    adjudicate_post_catalog,
    explicit_evidence_constraints,
)


def test_category_results_without_requirements_are_provisional_and_need_research():
    result = adjudicate_post_catalog(
        normalized_requirement_count=0,
        evidence_qualified_product_count=10,
        retrieval_count=10,
        material_attribute_coverage_gap=0.86,
        category_similarity_only=True,
    )
    assert result.evidence_qualified_product_count == 0
    assert result.qualification_authority == "none"
    assert result.research_needed is True
    assert "no_normalized_requirements" in result.reason_codes


def test_positive_requirements_and_fit_can_authorize_qualification():
    result = adjudicate_post_catalog(
        normalized_requirement_count=4,
        evidence_qualified_product_count=2,
        retrieval_count=5,
        material_attribute_coverage_gap=0.2,
    )
    assert result.qualification_authority == "positive_evidence"
    assert result.research_needed is False


def test_explicit_unresolved_support_constraint_blocks_authority():
    result = adjudicate_post_catalog(
        normalized_requirement_count=4,
        evidence_qualified_product_count=2,
        retrieval_count=5,
        material_attribute_coverage_gap=0.2,
        unresolved_explicit_constraints=["vendor_certification"],
    )
    assert result.qualification_authority == "none"
    assert result.research_needed is True


def test_explicit_evidence_constraints_are_workload_agnostic():
    assert explicit_evidence_constraints(
        "Only officially supported hardware; no unresolved critical firmware advisory."
    ) == ["vendor_certification", "security_status"]
    assert explicit_evidence_constraints("Show ordinary laptops") == []
