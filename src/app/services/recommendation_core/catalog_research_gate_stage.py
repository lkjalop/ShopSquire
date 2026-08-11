"""Typed post-retrieval research gate extracted from the recommendation core."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.recommendation_core.post_catalog_adjudicator import (
    PostCatalogAdjudication,
    adjudicate_post_catalog,
    explicit_evidence_constraints,
)
from src.app.services.recommendation_core.research_routing import (
    assess_research_trigger_shadow,
)


class CatalogResearchGateInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    semantic_proposal: Any = None
    semantic_authority_state: str | None = None
    query: str = ""
    retrieval_count: int = Field(ge=0)
    returned_product_count: int = Field(ge=0)
    normalized_requirement_count: int = Field(ge=0)
    qualified_product_count: int = Field(ge=0)
    unknown_requirement_count: int = Field(ge=0)
    possible_requirement_count: int = Field(ge=1)
    unresolved_explicit_constraints: list[str] = Field(default_factory=list, max_length=24)
    requested_quantity: int | None = Field(default=None, ge=1)


class CatalogResearchGateOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shadow_observation: dict[str, Any]
    adjudication: PostCatalogAdjudication


def run_catalog_research_gate(stage: CatalogResearchGateInput) -> CatalogResearchGateOutput:
    qualified_coverage = stage.qualified_product_count / max(1, stage.retrieval_count)
    unknown_gap = stage.unknown_requirement_count / stage.possible_requirement_count
    catalog_coverage_gap = 1.0 - qualified_coverage
    constraints = list(dict.fromkeys([
        *stage.unresolved_explicit_constraints,
        *explicit_evidence_constraints(stage.query),
    ]))
    shadow = assess_research_trigger_shadow(
        stage.semantic_proposal,
        semantic_authority_state=stage.semantic_authority_state,
        catalog_coverage=qualified_coverage,
        retrieval_confidence=stage.returned_product_count / max(1, stage.retrieval_count),
        unknown_attribute_ratio=unknown_gap,
        qualified_product_count=stage.qualified_product_count,
        commercial_materiality=(
            1.0 if stage.requested_quantity and stage.requested_quantity > 1 else 0.0
        ),
    ).model_dump()
    adjudication = adjudicate_post_catalog(
        normalized_requirement_count=stage.normalized_requirement_count,
        evidence_qualified_product_count=stage.qualified_product_count,
        retrieval_count=stage.retrieval_count,
        material_attribute_coverage_gap=max(unknown_gap, catalog_coverage_gap),
        unresolved_explicit_constraints=constraints,
        category_similarity_only=bool(
            stage.returned_product_count and stage.normalized_requirement_count == 0
        ),
    )
    return CatalogResearchGateOutput(shadow_observation=shadow, adjudication=adjudication)


__all__ = [
    "CatalogResearchGateInput", "CatalogResearchGateOutput", "run_catalog_research_gate",
]
