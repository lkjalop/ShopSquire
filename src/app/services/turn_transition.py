"""Canonical conversation transition and revision-bound turn projection contracts.

The language model may propose continuity, but this module owns the bounded
transition vocabulary consumed by the durable case reducer.  The resulting
read model is deliberately shared by chat, the buyer panel and Decision Trace.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.research_outcome import ResearchOutcome, build_research_outcome


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
    operation_id: str | None = Field(default=None, max_length=240)
    trace_id: str | None = Field(default=None, max_length=240)
    transition: TurnTransition
    objective: str | None = Field(default=None, max_length=2_000)
    buyer_query: str | None = Field(default=None, max_length=8_000)
    workloads: list[str] = Field(default_factory=list, max_length=20)
    preserved_fields: list[str] = Field(default_factory=list, max_length=40)
    cleared_fields: list[str] = Field(default_factory=list, max_length=40)
    shared_constraints: dict[str, Any] = Field(default_factory=dict)
    canonical_budget: dict[str, Any] | None = None
    commercial_terms: dict[str, Any] = Field(default_factory=dict)
    subject_role: Literal[
        "PROCURE_SUBJECT", "RUN_SUBJECT_ON_PRODUCT", "COMPATIBILITY_CHECK",
        "ADJACENT_PRODUCT", "UNRESOLVED",
    ] = "UNRESOLVED"
    case_patches: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    pending_clarification: PendingClarificationCommit = Field(
        default_factory=PendingClarificationCommit,
    )
    external_research_authorized: bool = False
    research: dict[str, Any] = Field(default_factory=dict)
    execution_evidence: dict[str, Any] = Field(default_factory=dict)
    semantic_scope: str | None = None
    source_intake_receipts: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    requirements: RequirementCommit = Field(default_factory=RequirementCommit)
    catalog_scope: dict[str, Any] | None = None
    catalog_authority: Literal["permitted", "blocked", "unknown"] = "unknown"
    commerce_authority: Literal["none"] = "none"
    assistant_message: str = Field(default="", max_length=8_000)
    right_panel: dict[str, Any] | None = None
    products: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    product_shelves: dict[str, Any] | None = None


class RevisionBoundTurnReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["revision-bound-turn-read-model.v1"] = (
        "revision-bound-turn-read-model.v1"
    )
    case_id: str
    operation_id: str | None = None
    case_revision: int = Field(ge=1)
    transition: TurnTransition
    objective: str | None = None
    buyer_query: str | None = None
    workloads: list[str] = Field(default_factory=list)
    preserved_fields: list[str] = Field(default_factory=list)
    cleared_fields: list[str] = Field(default_factory=list)
    shared_constraints: dict[str, Any] = Field(default_factory=dict)
    canonical_budget: dict[str, Any] | None = None
    commercial_terms: dict[str, Any] = Field(default_factory=dict)
    subject_role: Literal[
        "PROCURE_SUBJECT", "RUN_SUBJECT_ON_PRODUCT", "COMPATIBILITY_CHECK",
        "ADJACENT_PRODUCT", "UNRESOLVED",
    ] = "UNRESOLVED"
    pending_clarification: PendingClarificationCommit
    external_research_authorized: bool
    research: dict[str, Any] = Field(default_factory=dict)
    research_outcome: ResearchOutcome
    source_intake_receipts: list[dict[str, Any]] = Field(default_factory=list)
    requirements: RequirementCommit
    catalog_scope: dict[str, Any] | None = None
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
    # A case-bound additive receipt is stronger continuity evidence than a
    # model's generic ``switch`` proposal. The receipt is created only after a
    # literal additive operation and bounded workload identity were validated.
    # Explicit replacement turns never create it and still fall through to the
    # replacement branch below.
    if additive_workload:
        return TurnTransition.ADD_WORKLOAD
    if subject == "switch" or relation == "supersede":
        return TurnTransition.REPLACE_WORKLOAD
    if commercial_amendment:
        return TurnTransition.COMMERCIAL_AMENDMENT
    if pending_clarification and relation == "answer":
        return TurnTransition.ANSWER_PENDING
    if active_case and (workload_refinement or subject == "continue"):
        return TurnTransition.REFINE_WORKLOAD
    return TurnTransition.UNRESOLVED


def effective_turn_facts(literal_facts: Mapping[str, Any], *, canonical_budget: Mapping[str, Any] | None,
                         canonical_quantity: int | None = None,
                         accepted_budget: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Project accepted case constraints without rewriting literal buyer facts."""
    result = dict(literal_facts)
    literal_budget = result.get("literal_canonical_budget", result.get("canonical_budget"))
    result["literal_canonical_budget"] = literal_budget
    result["canonical_budget"] = dict(canonical_budget) if canonical_budget else None
    result["budget_source"] = ("buyer_turn" if literal_budget else
                               "accepted_case_constraints" if canonical_budget else "not_stated")
    result['literal_commercial_terms']=dict(result.get('literal_commercial_terms') or result.get('commercial_terms') or {})
    if accepted_budget:
        result['literal_budget_scope']=result.get('literal_budget_scope',result.get('budget_scope'))
        result['budget_scope']=accepted_budget.get('scope') or 'unknown'
        result['commercial_terms']={**(result.get('commercial_terms') or {}),
            'budget_scope':result['budget_scope'],'currency':accepted_budget.get('currency')}
    if type(canonical_quantity) is int and canonical_quantity>0:
        result['literal_quantity']=result.get('literal_quantity',result.get('quantity'))
        result['quantity']=canonical_quantity
        result['quantity_source']='accepted_case_constraints'
        result['commercial_terms']={**(result.get('commercial_terms') or {}),'quantity':canonical_quantity}
    return result


def build_turn_read_model(commit: TurnCommit, *, revision: int,
                         canonical_state: Mapping[str, Any] | None = None) -> RevisionBoundTurnReadModel:
    scope = ({**commit.catalog_scope, "case_id": commit.case_id, "case_revision": revision}
             if commit.catalog_scope else None)
    outcome = build_research_outcome(
        case_id=commit.case_id,
        case_revision=revision,
        operation_id=commit.operation_id,
        research=commit.research,
        requirements=commit.requirements.model_dump(mode="python"),
        catalog_authority=commit.catalog_authority,
        commerce_authority=commit.commerce_authority,
        contract_receipt=commit.research.get('requirement_contract'),
    )
    right_panel = dict(commit.right_panel or {})
    right_panel["canonical_budget"] = commit.canonical_budget
    right_panel["commercial_terms"] = dict(commit.commercial_terms)
    right_panel["subject_role"] = commit.subject_role
    right_panel["catalog_scope"] = scope
    effective_authority = outcome.catalog_authority if outcome.catalog_authority == "blocked" else commit.catalog_authority
    right_panel["catalog_authority"] = effective_authority
    from src.app.services.terminal_research_narration import terminal_research_narration
    message = terminal_research_narration(
        research_outcome=outcome.model_dump(mode="json"), execution_evidence=commit.execution_evidence,
        current_exploration=commit.research.get("ambiguity_exploration"),
        existing_message=commit.assistant_message,
        subject_role=commit.subject_role,
        product_shelves=commit.product_shelves,
        catalog_browse=right_panel.get('semantic_resolution'),
        catalog_product_count=len(commit.products) if effective_authority == 'permitted' else 0,
    )
    from src.app.services.chat_case_continuity import project_retained_facts, retained_facts_message
    view = {"case_id": commit.case_id, "case_revision": revision,
            "procurement_case_state": dict(canonical_state or {})}
    project_retained_facts(view)
    right_panel["retained_buyer_facts"] = view.get("retained_buyer_facts")
    summary = retained_facts_message(view.get("retained_buyer_facts") or {})
    if summary and not message.startswith(summary):
        message = summary + " " + message
    from src.app.services.chat_turn_projection import terminal_scope_contract
    right_panel.update(terminal_scope_contract(scope=scope, case_id=commit.case_id,
        case_revision=revision, applicable=commit.semantic_scope not in {"informational", "service_or_place"}))
    from src.app.services.terminal_qualification import terminal_questions
    pending = commit.pending_clarification.model_copy(deep=True)
    if pending.current:
        questions = terminal_questions([pending.current], outcome.model_dump(mode='json'))
        pending.current = questions[0] if questions else None
        if not questions:
            pending.action = 'consume'
    if commit.transition == TurnTransition.ADD_WORKLOAD and commit.workloads:
        workload_context = "Requested workloads: " + "; ".join(commit.workloads) + "."
        if not message.startswith(workload_context):
            message = workload_context + " " + message
    return RevisionBoundTurnReadModel(
        case_id=commit.case_id,
        operation_id=commit.operation_id,
        case_revision=revision,
        transition=commit.transition,
        objective=commit.objective,
        buyer_query=commit.buyer_query,
        workloads=list(commit.workloads),
        preserved_fields=list(commit.preserved_fields),
        cleared_fields=list(commit.cleared_fields),
        shared_constraints=dict(commit.shared_constraints),
        canonical_budget=(dict(commit.canonical_budget) if commit.canonical_budget else None),
        commercial_terms=dict(commit.commercial_terms),
        subject_role=commit.subject_role,
        pending_clarification=pending,
        external_research_authorized=commit.external_research_authorized,
        research=dict(commit.research),
        research_outcome=outcome,
        source_intake_receipts=list(commit.source_intake_receipts),
        requirements=commit.requirements,
        catalog_scope=scope,
        catalog_authority=effective_authority,
        commerce_authority=commit.commerce_authority,
        assistant_message=message,
        right_panel=right_panel,
        products=list(commit.products) if effective_authority == "permitted" else [],
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
