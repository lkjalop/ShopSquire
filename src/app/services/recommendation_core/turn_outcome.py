"""Canonical contracts spanning one recommendation turn.

Router branches may propose lane-specific values, but they never own canonical
buyer facts.  This module is the single reducer boundary applied to every router
exit before retrieval or presentation can consume the decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Tuple, Mapping, Optional, TYPE_CHECKING

from src.app.services.budget_grammar import BudgetParse
from src.app.services.commercial_terms import CommercialTerms

if TYPE_CHECKING:  # pragma: no cover - avoids a runtime import cycle
    from src.app.services.recommendation_core.envelope import TurnEnvelope


@dataclass(frozen=True)
class TurnDecision:
    lane: str = "SEARCH"
    node_handle: Optional[str] = None            # clamped to offered candidates
    node_path: Optional[str] = None
    # key -> [(op, thr), ...] — a predicate LIST so a range (floor AND ceiling) is one value
    # end-to-end (M2-B1); the router itself emits one predicate per key (the model's clamp).
    requirements: Dict[str, List[Tuple[str, float]]] = field(default_factory=dict)
    # Fulfilment/payment constraints are deliberately separate from product-fit predicates.
    # The model may propose only this closed vocabulary; deterministic services own clocks,
    # calendars, payment policy and all state changes.
    operational_constraints: Dict[str, Any] = field(default_factory=dict)
    use_cases: Tuple[str, ...] = ()              # model-classified, clamped to KB keys
    workload_entities: Tuple[Tuple[str, str], ...] = ()  # (game|software, literal name)
    audience_contexts: Tuple[str, ...] = ()      # context only; never weakens workload floors
    use_case_variants: Dict[str, str] = field(default_factory=dict)  # use-case -> registry variant
    refusal_granted: bool = False                # sells_within()==False confirmed the refusal
    confidence: float = 0.0
    source: str = "model"                        # model | default
    # TWO-SLOT INTENT (M3-C1): the shopper's message carries a DEVICE they want to buy and,
    # separately, WORKLOADS they'll run on it. 'play valorant on a laptop' = device Laptops +
    # workload Video-Game-Software, relationship run_on. Derived deterministically from the
    # routed node's vertical (so-/me- = a workload, not a device); node_handle stays the
    # retrieval target (rerouted to the device for a run_on turn).
    requested_product_node: Optional[str] = None   # the DEVICE to retrieve (== node_handle)
    requested_category_label: Optional[str] = None  # buyer-facing label when taxonomy is approximate
    exact_product_sku: Optional[str] = None          # indexed literal alias; never fuzzy/model-selected
    # Closed model signal for requests outside product commerce. It is advisory until the clamp
    # confirms there is no grounded product node; it can never suppress a catalog result.
    request_scope: str = "uncertain"               # product | service_or_place | uncertain
    workloads: Tuple[str, ...] = ()                # content/software nodes named as workloads
    relationship: str = "buy"                      # buy (named a product) | run_on (named a workload)
    subject_role: str = "UNRESOLVED"                # validated semantics; never sellability authority
    # SESSION (M3-C2): the prior turn's shortlist SKUs. CONSUMED since R9.4 (review-6 #17
    # closed): an EXPLAIN/COMPARE turn whose subject came from the session retrieves exactly
    # these SKUs in shown order ('the first one' = cards[0] of what the shopper actually saw).
    prior_shortlist: Tuple[str, ...] = ()
    # REFINEMENTS (R9.2 — the FILTER-executor slots): the model NAMES the narrowing, clamps
    # keep it grounded — brand must be a REAL catalog brand (case-insensitive → canonical DB
    # casing), sort ∈ ranking.SORTS. A miss drops the refinement, never invents one.
    brand_filter: Optional[str] = None
    sort: Optional[str] = None
    # SOFT brand preference (Phase 1d) — distinct from the HARD brand_filter above: 'ideally a Mac'
    # must NOT remove non-Apple options, it should surface an Apple 'preference' band on the shelf.
    # Clamped to a real catalog brand; nulled when it equals a hard brand_filter (already narrowed).
    preferred_brand: Optional[str] = None
    # brand EXCLUSION ('a gaming laptop but NOT Apple') — the negation slot the V2 core was missing;
    # clamped to a real catalog brand, subtracted at retrieval AND from the capability floor.
    exclude_brand: Optional[str] = None
    # keep | set | clear. A separate operation is required because null brand fields mean
    # "not mentioned this turn" and must not also mean "remove remembered constraints".
    brand_action: str = "keep"
    # R9.4: True when the routed node came from the SESSION (nodeless-continuation inherit or
    # fragment-drift override) — the turn is ABOUT the prior subject, so EXPLAIN/COMPARE may
    # consume prior_shortlist ('the first one' = the items actually shown last turn).
    subject_from_session: bool = False
    # R9.3: the specific products the shopper NAMED in a compare ('the Dell G16 vs the Lenovo
    # Legion') — model-named short strings; the CORE binds each to a retrieved variant by
    # distinctive-token overlap and narrows only when ≥2 bind unambiguously (never guess a
    # comparison down to the wrong units). Empty = whole-category compare.
    compare_targets: Tuple[str, ...] = ()
    # BULK (Phase 1f — model-judged, not regex): the shopper's ORDER SIZE and TOTAL budget for a
    # bulk/procurement ask ('20 laptops … $16000 total'). Model EXTRACTS; the clamp bounds them to
    # sane values. quantity is a count, not a fit predicate; total_budget is the whole-order budget
    # (distinct from the per-unit budget the platform already applies at retrieval).
    quantity: Optional[int] = None
    # True only when the shared quantity grammar anchored the count in this buyer turn.
    # Model output and inherited session values may aid interpretation, but cannot independently
    # authorize consequential commercial state for a switched or unresolved subject.
    quantity_explicit: bool = False
    total_budget_cents: Optional[int] = None
    # per_unit | total | unknown — whether a STATED budget is per-item or the whole-order total.
    # NEVER reinterpret a per-unit budget as a total (the arithmetic-safety invariant, review-10 P0).
    budget_scope: str = "unknown"
    # How the shopper expressed the maximum. It controls clarification/stretch presentation,
    # never authorization: the primary slate remains inside the cap for every mode.
    budget_cap_mode: str = "hard"          # hard | soft | ambiguous
    # continue | switch | uncertain (review-10 P0.2) — the model's LANE-INDEPENDENT continuation
    # signal; drives prior-subject inheritance and suppresses fragment-drift on an explicit switch.
    subject_action: str = "uncertain"
    # current_order | general_policy | none. Kept separate from subject continuity so an omitted
    # quantity can only be inherited for a real active procurement workflow.
    procurement_context: str = "none"
    # none | status | summary. Read-only case operations are resolved from the
    # existing sealed session and never authorize fresh catalog retrieval.
    case_operation: str = "none"
    # A turn may ask for an explanation while also changing bounded constraints. The primary
    # lane performs the consequential read (normally FILTER); secondary lanes describe the
    # additional response obligation without inventing another execution path.
    secondary_lanes: Tuple[str, ...] = ()
    # Relationship between this turn and a server-persisted material question.
    # The model interprets the dialogue relation; deterministic state ownership
    # decides whether the pending envelope is consumed, suspended, or retained.
    clarification_relation: str = "none"  # none | answer | interrupt | supersede | ambiguous
    # When the model selects a product class that the buyer did not name and it conflicts with
    # the declared workload host, retrieval must stop and ask which product type they meant.
    product_type_options: Tuple[str, ...] = ()
    # Audit-only, bounded copy of the model's semantic proposal before platform clamps. This is
    # never consumed by retrieval or execution; it exists so the trace can prove which component
    # proposed a value and which component authorized the final decision.
    model_proposal: Dict[str, Any] = field(default_factory=dict)
    # Generic, non-executable interpretation of unfamiliar concepts.  Product/domain facts
    # never live here: the model proposes ambiguity and evidence questions; the semantic
    # reducer decides whether catalog retrieval may proceed.
    semantic_proposal: Dict[str, Any] = field(default_factory=dict)
    coverage_abstention_shadow: Dict[str, Any] = field(default_factory=dict)
    authorization_changes: Tuple[str, ...] = ()
    # Open-vocabulary state proposal. The model proposes operations over a typed
    # case; the durable reducer validates revision/invariants and owns acceptance.
    # These operations never grant commerce authority.
    case_patches: Tuple[Dict[str, Any], ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {"lane": self.lane, "node_handle": self.node_handle, "node_path": self.node_path,
                "requirements": {k: [list(p) for p in v] for k, v in self.requirements.items()},
                "operational_constraints": dict(self.operational_constraints),
                "use_cases": list(self.use_cases), "refusal_granted": self.refusal_granted,
                "workload_entities": [
                    {"kind": kind, "name": name} for kind, name in self.workload_entities
                ],
                "audience_contexts": list(self.audience_contexts),
                "use_case_variants": dict(self.use_case_variants),
                "confidence": round(self.confidence, 3), "source": self.source,
                "requested_product_node": self.requested_product_node,
                "requested_category_label": self.requested_category_label,
                "exact_product_sku": self.exact_product_sku,
                "request_scope": self.request_scope,
                "workloads": list(self.workloads), "relationship": self.relationship,
                "subject_role": self.subject_role,
                "prior_shortlist": list(self.prior_shortlist),
                "brand_filter": self.brand_filter, "sort": self.sort,
                "preferred_brand": self.preferred_brand, "exclude_brand": self.exclude_brand,
                "brand_action": self.brand_action,
                "subject_from_session": self.subject_from_session,
                "compare_targets": list(self.compare_targets),
                "quantity": self.quantity, "quantity_explicit": self.quantity_explicit,
                "total_budget_cents": self.total_budget_cents,
                "budget_scope": self.budget_scope, "budget_cap_mode": self.budget_cap_mode,
                "subject_action": self.subject_action,
                "procurement_context": self.procurement_context,
                "case_operation": self.case_operation,
                "secondary_lanes": list(self.secondary_lanes),
                "clarification_relation": self.clarification_relation,
                "product_type_options": list(self.product_type_options),
                "model_proposal": dict(self.model_proposal),
                "semantic_proposal": dict(self.semantic_proposal),
                "coverage_abstention_shadow": dict(self.coverage_abstention_shadow),
                "authorization_changes": list(self.authorization_changes),
                "case_patches": [dict(item) for item in self.case_patches]}


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
