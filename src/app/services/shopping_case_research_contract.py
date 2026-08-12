"""Typed buyer-safe contract for the two governed research execution lanes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.case_research_plan import CaseResearchPlan


class ShoppingCaseResearchExecutionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["shopping-case-research-execution-v1"] = (
        "shopping-case-research-execution-v1"
    )
    research_plan_id: str
    publisher_status: Literal["resolved_enrolled", "unresolved"]
    execution_lane: Literal["enrolled_official_sources", "publisher_resolution"]
    source_candidate_ids: list[str] = Field(default_factory=list)
    publisher_approval_required: bool
    qualification_authority: Literal["none", "requirements"] = "none"
    cart_authority: Literal["none"] = "none"


def project_research_execution_contract(
    plan: CaseResearchPlan,
    *,
    requirements_compiled: bool = False,
) -> ShoppingCaseResearchExecutionContract:
    unresolved = plan.publisher_status == "unresolved"
    return ShoppingCaseResearchExecutionContract(
        research_plan_id=plan.plan_id,
        publisher_status=plan.publisher_status,
        execution_lane=(
            "publisher_resolution" if unresolved else "enrolled_official_sources"
        ),
        source_candidate_ids=list(plan.source_candidate_ids),
        publisher_approval_required=unresolved,
        qualification_authority="requirements" if requirements_compiled else "none",
    )


__all__ = [
    "ShoppingCaseResearchExecutionContract",
    "project_research_execution_contract",
]
