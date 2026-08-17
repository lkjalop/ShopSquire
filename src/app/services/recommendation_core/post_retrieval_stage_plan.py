"""Artifact-emitting post-retrieval stage plan for the core strangler."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from src.app.services.recommendation_core.typed_stage_coordinator import (
    CoordinatedStage,
    RecommendationPhase,
)


def build_post_retrieval_stage_plan(
    operations: Mapping[str, Callable[[], None]],
) -> tuple[CoordinatedStage, ...]:
    required = {
        "capability_budget", "shelf", "variant_clarify", "complement_offer",
        "bulk_economics", "fulfillment_preview", "secondary_explanation",
    }
    missing = required.difference(operations)
    if missing:
        raise ValueError(f"post_retrieval_stage_operation_missing:{','.join(sorted(missing))}")
    return (
        CoordinatedStage(
            RecommendationPhase.FIT, "capability_budget", operations["capability_budget"],
            stage_id="fit-capability-budget",
            input_artifact_refs=("requirements:accepted", "catalog:ranked", "budget:buyer"),
            output_artifact_refs=("fit:budget-verdicts",),
        ),
        CoordinatedStage(
            RecommendationPhase.FIT, "shelf", operations["shelf"], stage_id="fit-shelf",
            input_artifact_refs=("fit:budget-verdicts", "catalog:exact"),
            output_artifact_refs=("fit:shelves",),
            dependency_stage_ids=("fit-capability-budget",),
        ),
        CoordinatedStage(
            RecommendationPhase.FIT, "variant_clarify", operations["variant_clarify"],
            stage_id="fit-variant-clarify",
            input_artifact_refs=("fit:shelves", "interpretation:hypotheses"),
            output_artifact_refs=("fit:material-question",),
            dependency_stage_ids=("fit-shelf",),
        ),
        CoordinatedStage(
            RecommendationPhase.COMMERCIAL, "complement_offer", operations["complement_offer"],
            stage_id="commercial-complement",
            input_artifact_refs=("fit:shelves", "catalog:complements", "inventory:current"),
            output_artifact_refs=("commercial:complement-options",),
            dependency_stage_ids=("fit-shelf",),
        ),
        CoordinatedStage(
            RecommendationPhase.COMMERCIAL, "bulk_economics", operations["bulk_economics"],
            stage_id="commercial-bulk-economics",
            input_artifact_refs=("fit:shelves", "budget:buyer", "quantity:buyer"),
            output_artifact_refs=("commercial:bulk-options",),
            dependency_stage_ids=("fit-shelf",),
        ),
        CoordinatedStage(
            RecommendationPhase.COMMERCIAL, "fulfillment_preview", operations["fulfillment_preview"],
            stage_id="fulfilment-preview",
            input_artifact_refs=("commercial:bulk-options", "inventory:current", "deadline:buyer"),
            output_artifact_refs=("fulfilment:options",),
            dependency_stage_ids=("commercial-bulk-economics",),
        ),
        CoordinatedStage(
            RecommendationPhase.RESPONSE, "secondary_explanation", operations["secondary_explanation"],
            stage_id="response-explanation",
            input_artifact_refs=("fit:shelves", "fulfilment:options", "evidence:watermarks"),
            output_artifact_refs=("response:buyer-projection",),
            dependency_stage_ids=("fit-shelf", "fulfilment-preview"),
        ),
    )


__all__ = ["build_post_retrieval_stage_plan"]
