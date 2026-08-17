import pytest

from src.app.services.recommendation_core.post_retrieval_stage_plan import (
    build_post_retrieval_stage_plan,
)


def test_post_retrieval_plan_declares_real_artifact_lineage():
    names = (
        "capability_budget", "shelf", "variant_clarify", "complement_offer",
        "bulk_economics", "fulfillment_preview", "secondary_explanation",
    )
    stages = build_post_retrieval_stage_plan({name: lambda: None for name in names})
    shelf = next(row for row in stages if row.name == "shelf")
    fulfilment = next(row for row in stages if row.name == "fulfillment_preview")
    assert shelf.input_artifact_refs == ("fit:budget-verdicts", "catalog:exact")
    assert shelf.output_artifact_refs == ("fit:shelves",)
    assert fulfilment.dependency_stage_ids == ("commercial-bulk-economics",)


def test_post_retrieval_plan_fails_before_execution_when_operation_missing():
    with pytest.raises(ValueError, match="post_retrieval_stage_operation_missing:shelf"):
        build_post_retrieval_stage_plan({
            "capability_budget": lambda: None,
            "variant_clarify": lambda: None,
            "complement_offer": lambda: None,
            "bulk_economics": lambda: None,
            "fulfillment_preview": lambda: None,
            "secondary_explanation": lambda: None,
        })
