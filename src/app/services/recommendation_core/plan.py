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
from typing import Any, Dict, List, Optional

from src.app.services.recommendation_core.turn_router import TurnDecision

TOOLS = ("retrieve", "fit_check", "off_catalog_honesty", "clarify", "policy_answer",
         "handoff_support", "handoff_procurement")

# lanes → deterministic default plans (the derivation table IS the spec of lane behavior)
_LANE_PLANS: Dict[str, List[str]] = {
    "SEARCH": ["retrieve", "fit_check"],
    "FILTER": ["retrieve", "fit_check"],
    "COMPARE": ["retrieve", "fit_check"],
    "EXPLAIN": ["retrieve", "fit_check"],
    "INVENTORY": ["retrieve"],
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

    def as_dict(self) -> Dict[str, Any]:
        return {"steps": list(self.steps), "source": self.source, "plan_version": "core-v1"}


def derive_plan(decision: TurnDecision) -> Plan:
    steps = list(_LANE_PLANS.get(decision.lane, ["retrieve"]))
    # honesty guard at derivation too: an ungranted refusal can never be planned
    if "off_catalog_honesty" in steps and not decision.refusal_granted:
        steps = ["retrieve", "fit_check"]
    if "fit_check" in steps and not decision.requirements:
        steps.remove("fit_check")          # nothing to check — don't fabricate a verdict step
    return Plan(steps=steps, source="derived")


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
