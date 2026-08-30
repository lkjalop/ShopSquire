"""Canonical conversation transition and revision-bound turn projection contracts.

The language model may propose continuity, but this module owns the bounded
transition vocabulary consumed by the durable case reducer.  The resulting
read model is deliberately shared by chat, the buyer panel and Decision Trace.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field


class TurnTransition(str, Enum):
    ANSWER_PENDING = "ANSWER_PENDING"
    REFINE_WORKLOAD = "REFINE_WORKLOAD"
    ADD_WORKLOAD = "ADD_WORKLOAD"
    REPLACE_WORKLOAD = "REPLACE_WORKLOAD"
    COMMERCIAL_AMENDMENT = "COMMERCIAL_AMENDMENT"
    NEW_CATEGORY = "NEW_CATEGORY"
    UNRESOLVED = "UNRESOLVED"


class PendingClarificationCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["none", "retain", "consume", "suspend", "replace"] = "none"
    prior_question_id: str | None = Field(default=None, max_length=120)
    current: dict[str, Any] | None = None


class RequirementCommit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    rejected: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    unresolved: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class TurnCommit(BaseModel):
    """All durable facts accepted from one buyer turn before one CAS commit."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["case-turn-commit.v1"] = "case-turn-commit.v1"
    case_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(ge=1)
    source_message_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=200)
    trace_id: str | None = Field(default=None, max_length=240)
    transition: TurnTransition
    objective: str | None = Field(default=None, max_length=2_000)
    workloads: list[str] = Field(default_factory=list, max_length=20)
    preserved_fields: list[str] = Field(default_factory=list, max_length=40)
    cleared_fields: list[str] = Field(default_factory=list, max_length=40)
    shared_constraints: dict[str, Any] = Field(default_factory=dict)
    case_patches: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    pending_clarification: PendingClarificationCommit = Field(
        default_factory=PendingClarificationCommit,
    )
    external_research_authorized: bool = False
    research: dict[str, Any] = Field(default_factory=dict)
    source_intake_receipts: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    requirements: RequirementCommit = Field(default_factory=RequirementCommit)
    catalog_authority: Literal["permitted", "blocked", "unknown"] = "unknown"
    commerce_authority: Literal["none"] = "none"
    assistant_message: str = Field(default="", max_length=8_000)
    right_panel: dict[str, Any] | None = None
    products: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class RevisionBoundTurnReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["revision-bound-turn-read-model.v1"] = (
        "revision-bound-turn-read-model.v1"
    )
    case_id: str
    case_revision: int = Field(ge=1)
    transition: TurnTransition
    objective: str | None = None
    workloads: list[str] = Field(default_factory=list)
    preserved_fields: list[str] = Field(default_factory=list)
    cleared_fields: list[str] = Field(default_factory=list)
    shared_constraints: dict[str, Any] = Field(default_factory=dict)
    pending_clarification: PendingClarificationCommit
    external_research_authorized: bool
    research: dict[str, Any] = Field(default_factory=dict)
    source_intake_receipts: list[dict[str, Any]] = Field(default_factory=list)
    requirements: RequirementCommit
    catalog_authority: Literal["permitted", "blocked", "unknown"]
    commerce_authority: Literal["none"] = "none"
    assistant_message: str = ""
    right_panel: dict[str, Any] | None = None
    products: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str | None = None


def derive_turn_transition(
    *,
    active_case: bool,
    pending_clarification: Mapping[str, Any] | None = None,
    clarification_relation: str | None = None,
    subject_action: str | None = None,
    additive_workload: bool = False,
    commercial_amendment: bool = False,
    new_category: bool = False,
    workload_refinement: bool = False,
) -> TurnTransition:
    """Resolve one transition using explicit deterministic signals first."""

    relation = str(clarification_relation or "").strip().lower()
    subject = str(subject_action or "").strip().lower()
    if new_category:
        return TurnTransition.NEW_CATEGORY
    if subject == "switch" or relation == "supersede":
        return TurnTransition.REPLACE_WORKLOAD
    if additive_workload:
        return TurnTransition.ADD_WORKLOAD
    if commercial_amendment:
        return TurnTransition.COMMERCIAL_AMENDMENT
    if pending_clarification and relation == "answer":
        return TurnTransition.ANSWER_PENDING
    if active_case and (workload_refinement or subject == "continue"):
        return TurnTransition.REFINE_WORKLOAD
    return TurnTransition.UNRESOLVED


def build_turn_read_model(commit: TurnCommit, *, revision: int) -> RevisionBoundTurnReadModel:
    return RevisionBoundTurnReadModel(
        case_id=commit.case_id,
        case_revision=revision,
        transition=commit.transition,
        objective=commit.objective,
        workloads=list(commit.workloads),
        preserved_fields=list(commit.preserved_fields),
        cleared_fields=list(commit.cleared_fields),
        shared_constraints=dict(commit.shared_constraints),
        pending_clarification=commit.pending_clarification,
        external_research_authorized=commit.external_research_authorized,
        research=dict(commit.research),
        source_intake_receipts=list(commit.source_intake_receipts),
        requirements=commit.requirements,
        catalog_authority=commit.catalog_authority,
        commerce_authority=commit.commerce_authority,
        assistant_message=commit.assistant_message,
        right_panel=commit.right_panel,
        products=list(commit.products),
        trace_id=commit.trace_id,
    )


__all__ = [
    "PendingClarificationCommit",
    "RequirementCommit",
    "RevisionBoundTurnReadModel",
    "TurnCommit",
    "TurnTransition",
    "build_turn_read_model",
    "derive_turn_transition",
]
