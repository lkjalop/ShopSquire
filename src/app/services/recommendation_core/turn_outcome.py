"""Canonical contracts spanning one recommendation turn.

Router branches may propose lane-specific values, but they never own canonical
buyer facts.  This module is the single reducer boundary applied to every router
exit before retrieval or presentation can consume the decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, TYPE_CHECKING

from src.app.services.budget_grammar import BudgetParse
from src.app.services.commercial_terms import CommercialTerms

if TYPE_CHECKING:  # pragma: no cover - avoids a runtime import cycle
    from src.app.services.recommendation_core.envelope import TurnEnvelope
    from src.app.services.recommendation_core.turn_router import TurnDecision


@dataclass(frozen=True)
class EntityFrame:
    identity: Optional[str] = None
    entity_category: str = "unknown"
    turn_role: str = "UNRESOLVED"
    buyer_span: Optional[str] = None
    confidence: float = 0.0
    authority: str = "proposed"


@dataclass(frozen=True)
class SemanticProposal:
    entity: EntityFrame = field(default_factory=EntityFrame)
    source: str = "none"
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolPlan:
    capabilities: tuple[str, ...] = ()
    authorization_basis: str = "none"
    operation_id: Optional[str] = None
    max_provider_fanout: int = 0
    total_deadline_ms: int = 0


@dataclass(frozen=True)
class TurnFacts:
    buyer_query: str
    budget: Optional[BudgetParse]
    commercial_terms: CommercialTerms
    quantity: Optional[int]
    budget_scope: str
    total_budget_cents: Optional[int]

    @classmethod
    def from_envelope(
        cls,
        envelope: "TurnEnvelope",
        *,
        decision: Optional["TurnDecision"] = None,
    ) -> "TurnFacts":
        budget = envelope.budget_parse
        quantity = getattr(decision, "quantity", None) if decision is not None else None
        if quantity is None:
            quantity = envelope.commercial_terms.quantity
        scope = str(getattr(decision, "budget_scope", "") or "").lower()
        if scope not in {"total", "per_unit"}:
            scope = str(envelope.commercial_terms.budget_scope or "unknown").lower()
        if scope not in {"total", "per_unit"}:
            scope = "unknown"
        total = getattr(decision, "total_budget_cents", None) if decision is not None else None
        if total is None and scope == "total" and envelope.budget_max_cents is not None:
            total = int(envelope.budget_max_cents)
        return cls(
            buyer_query=str(envelope.buyer_query or envelope.query or ""),
            budget=budget,
            commercial_terms=envelope.commercial_terms,
            quantity=(int(quantity) if quantity is not None else None),
            budget_scope=scope,
            total_budget_cents=(int(total) if total is not None else None),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "buyer_query": self.buyer_query,
            "canonical_budget": self.budget.to_dict() if self.budget else None,
            "commercial_terms": self.commercial_terms.to_dict(),
            "quantity": self.quantity,
            "budget_scope": self.budget_scope,
            "total_budget_cents": self.total_budget_cents,
        }


@dataclass(frozen=True)
class TurnOutcome:
    facts: TurnFacts
    semantic: SemanticProposal
    tool_plan: ToolPlan
    decision: "TurnDecision"


def finalize_turn_decision(
    decision: "TurnDecision",
    envelope: "TurnEnvelope",
    *,
    db: Any = None,
) -> TurnOutcome:
    """Apply canonical facts and semantic validation to every router exit."""
    from src.app.services.subject_role import validate_entity_frame, validate_subject_role

    raw = dict(getattr(decision, "model_proposal", None) or {})
    entity = validate_entity_frame(
        envelope.buyer_query or envelope.query,
        raw.get("entity_frame") if isinstance(raw.get("entity_frame"), dict) else raw,
        fallback_role=str(getattr(decision, "subject_role", "") or "UNRESOLVED"),
    )
    role = validate_subject_role(
        envelope.buyer_query or envelope.query,
        node_handle=getattr(decision, "node_handle", None),
        sold_state=None,
        model_proposal=entity.turn_role,
    )
    facts = TurnFacts.from_envelope(envelope, decision=decision)
    finalized = replace(
        decision,
        subject_role=role.value,
        quantity=(facts.quantity if facts.quantity is not None else decision.quantity),
        total_budget_cents=(
            facts.total_budget_cents
            if facts.total_budget_cents is not None else decision.total_budget_cents
        ),
        budget_scope=facts.budget_scope,
    )
    capabilities: tuple[str, ...] = ()
    semantic_payload = dict(getattr(finalized, "semantic_proposal", None) or {})
    evidence_needs = semantic_payload.get("evidence_needs")
    if isinstance(evidence_needs, list):
        capabilities = tuple(str(value) for value in evidence_needs[:4] if str(value))
    return TurnOutcome(
        facts=TurnFacts.from_envelope(envelope, decision=finalized),
        semantic=SemanticProposal(entity=entity, source=str(finalized.source), raw=raw),
        tool_plan=ToolPlan(capabilities=capabilities),
        decision=finalized,
    )


__all__ = [
    "EntityFrame", "SemanticProposal", "ToolPlan", "TurnFacts", "TurnOutcome",
    "finalize_turn_decision",
]
