"""Plan stage (V2 Phase 4, step 3) — a bounded execution plan from a routed turn.

llm_planner._validate_plan generalized: the plan is a LIST OF STEPS drawn from a CLOSED TOOL
VOCABULARY, each tool mapping to one deterministic executor in the orchestrator. Two sources:

  derive_plan()  — deterministic plan from the TurnDecision (always available, always valid;
                   the fallback AND the acceptance baseline).
  propose_plan() — the model may REORDER/EXTEND within the vocabulary (adding clarify before
                   retrieve on ambiguity, a fit check the derivation missed). Every proposal
                   crosses validate_plan(); any miss → the derived plan. The model can add a
                   step; it can never add a CAPABILITY.

Tool vocabulary (executors in core.py — adding a tool means adding an executor + a test):
  retrieve            — facade evidence for the routed node/query (budget applied at edge)
  fit_check           — attribute-registry verdicts for the decision's requirements
  off_catalog_honesty — grounded refusal + supplier-RFQ offer (only with refusal_granted)
  clarify             — ask ONE bounded question instead of guessing
  policy_answer       — capability/policy honesty lane
  handoff_support     — post-purchase claims rail
  handoff_procurement — bulk/RFQ rail
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from src.app.services.recommendation_core.turn_router import TurnDecision

TOOLS = ("retrieve", "fit_check", "off_catalog_honesty", "clarify", "policy_answer",
         "handoff_support", "handoff_procurement")

# lanes → deterministic default plans (the derivation table IS the spec of lane behavior)
_LANE_PLANS: Dict[str, List[str]] = {
    "SEARCH": ["retrieve", "fit_check"],
    "FILTER": ["retrieve", "fit_check"],
    "COMPARE": ["retrieve", "fit_check"],
    "EXPLAIN": ["retrieve", "fit_check"],
    "INVENTORY": ["retrieve", "inventory_summary"],
    "OFF_CATALOG": ["off_catalog_honesty"],
    "POLICY_QUESTION": ["policy_answer"],
    "SUPPORT_CLAIM": ["handoff_support"],
    "CART_MUTATE": ["retrieve"],           # cart rail lives on chat; here it degrades to search
    # Procurement recommendation is still read-only, but it must produce the same authorized
    # catalog slate as a search before projecting bulk/sourcing advice. Consequential execution
    # remains in fulfillment_cases behind its existing confirmation and send gates.
    "PROCUREMENT": ["retrieve", "fit_check", "handoff_procurement"],
}


@dataclass(frozen=True)
class Plan:
    steps: List[str] = field(default_factory=lambda: ["retrieve"])
    source: str = "derived"                # derived | model
    needs_concept_resolution: bool = False
    semantic_proposal: Dict[str, Any] = field(default_factory=dict)
    semantic_authority_state: Literal[
        "not_material", "covered", "unresolved", "ambiguous",
        "uninterpreted_material", "invalid_proposal", "unsupported",
    ] = "not_material"
    external_research_authorized: bool = False
    research_plan: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "steps": list(self.steps),
            "source": self.source,
            "plan_version": "core-v2-semantic",
            "needs_concept_resolution": self.needs_concept_resolution,
            "semantic_proposal": dict(self.semantic_proposal),
            "semantic_authority_state": self.semantic_authority_state,
            "external_research_authorized": self.external_research_authorized,
            "research_plan": dict(self.research_plan),
        }


def derive_plan(decision: TurnDecision) -> Plan:
    if decision.lane == "PROCUREMENT" and decision.case_operation in (
        "status", "summary", "amendment",
    ):
        return Plan(steps=["handoff_procurement"], source="derived")
    steps = list(_LANE_PLANS.get(decision.lane, ["retrieve"]))
    # honesty guard at derivation too: an ungranted refusal can never be planned
    if "off_catalog_honesty" in steps and not decision.refusal_granted:
        steps = ["retrieve", "fit_check"]
    if "fit_check" in steps and not decision.requirements:
        steps.remove("fit_check")          # nothing to check — don't fabricate a verdict step
    semantic = dict(decision.semantic_proposal or {})
    coverage = dict(decision.coverage_abstention_shadow or {})
    model_material = _has_material_concept(semantic)
    coverage_material = _has_material_concept(coverage)
    subject_replaced = decision.clarification_relation in {"interrupt", "supersede"}
    bounded_workload_grounding = bool(
        decision.product_type_options
        or (
            not subject_replaced
            and (
                decision.requirements
                or decision.workload_entities
                or decision.relationship == "run_on"
                or decision.use_cases
            )
        )
    )
    if semantic.get("validation") == "valid" and model_material:
        effective_semantic = semantic
        hypotheses = [
            item for item in (semantic.get("workload_hypotheses") or [])
            if isinstance(item, dict)
        ]
        unknowns = [
            item for item in (semantic.get("material_unknowns") or [])
            if isinstance(item, dict) and bool(item.get("material", True))
        ]
        unresolved_concepts = any(
            isinstance(item, dict)
            and bool(item.get("material", True))
            and str(item.get("status") or "unresolved") != "resolved"
            for item in (semantic.get("concepts") or [])
        )
        state = "ambiguous" if len(hypotheses) > 1 else (
            "unresolved" if unknowns or unresolved_concepts else "covered"
        )
    elif (
        coverage.get("validation") == "valid"
        and coverage_material
        and not bounded_workload_grounding
    ):
        effective_semantic = coverage
        state = "uninterpreted_material"
    elif semantic.get("validation") == "rejected":
        effective_semantic = semantic
        state = "invalid_proposal"
    else:
        effective_semantic = semantic
        state = "not_material"
    needs_concept = state in {
        "unresolved", "ambiguous", "uninterpreted_material", "unsupported",
    }
    return Plan(
        steps=steps,
        source="derived",
        needs_concept_resolution=needs_concept,
        semantic_proposal=effective_semantic,
        semantic_authority_state=state,
    )


def _has_material_concept(proposal: Dict[str, Any]) -> bool:
    return any(
        isinstance(item, dict) and bool(item.get("material"))
        for item in (proposal.get("concepts") or [])
    )


def validate_plan(candidate: Any, decision: TurnDecision) -> Optional[Plan]:
    """Clamp a proposed plan: list of known tools, no duplicates, ≤5 steps, refusal only when
    granted, handoffs only on their lanes. None on any miss → caller uses derive_plan()."""
    if not isinstance(candidate, (list, tuple)) or not 0 < len(candidate) <= 5:
        return None
    steps = [str(s).strip() for s in candidate]
    if len(set(steps)) != len(steps) or any(s not in TOOLS for s in steps):
        return None
    if "off_catalog_honesty" in steps and not decision.refusal_granted:
        return None
    if "handoff_support" in steps and decision.lane != "SUPPORT_CLAIM":
        return None
    if "handoff_procurement" in steps and decision.lane != "PROCUREMENT":
        return None
    return Plan(steps=steps, source="model")
