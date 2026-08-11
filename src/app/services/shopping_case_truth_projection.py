"""One buyer/trace truth projection for an ambiguous shopping case."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.app.services.case_research_plan import (
    CaseAmbiguityObject,
    CaseResearchHypothesis,
    CaseResearchObligation,
)


class CaseQuestionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=3, max_length=500)


class ProviderAccountingProjection(BaseModel):
    model_config = ConfigDict(extra="allow")

    external_calls: int = Field(ge=0)
    paid_calls: int | None = Field(default=None, ge=0)


class ShoppingCaseTruthProjection(BaseModel):
    """Canonical projection consumed verbatim by both panel and Decision Trace."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["ambiguity-exploration-v1"] = "ambiguity-exploration-v1"
    case_id: str = Field(pattern=r"^sc-.+")
    trace_id: str = Field(min_length=1, max_length=240)
    retained_purpose: str = Field(min_length=3, max_length=500)
    status: Literal["provisional", "researched", "context_only", "unresolved"]
    interpretations: list[CaseResearchHypothesis] = Field(min_length=1, max_length=3)
    next_question: CaseQuestionProjection
    research_choices: list[str] = Field(default_factory=list, max_length=8)
    execution: str = Field(min_length=2, max_length=100)
    evidence: str = Field(min_length=2, max_length=100)
    decision: str = Field(min_length=2, max_length=100)
    cart_authority: Literal["none"] = "none"
    provider_accounting: ProviderAccountingProjection
    discovery_readiness: dict = Field(default_factory=dict)
    research_plan_id: str = Field(pattern=r"^crp-[a-f0-9]{20}$")
    ambiguity_objects: list[CaseAmbiguityObject] = Field(min_length=1, max_length=8)
    research_obligations: list[CaseResearchObligation] = Field(min_length=1, max_length=16)
    source_candidate_ids: list[str] = Field(default_factory=list, max_length=16)
    publisher_candidates: list[dict] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_case_identity_and_hypotheses(self) -> "ShoppingCaseTruthProjection":
        if self.trace_id != self.case_id.removeprefix("sc-"):
            raise ValueError("case_trace_identity_mismatch")
        hypothesis_ids = {row.hypothesis_id for row in self.interpretations}
        for ambiguity in self.ambiguity_objects:
            if not set(ambiguity.hypothesis_ids).issubset(hypothesis_ids):
                raise ValueError("ambiguity_hypothesis_mismatch")
        return self
