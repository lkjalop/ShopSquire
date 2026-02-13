from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from src.app.services.agent_types import AGENT_PHASES, AgentType, agent_type_for_name


@dataclass(frozen=True)
class AgentContract:
    name: str
    phase: str
    agent_type: AgentType
    required: bool = True


DEFAULT_AGENT_CONTRACTS: List[AgentContract] = [
    AgentContract("NLP Explore", "phase1", AgentType.EXPLORE),
    AgentContract("CV Explore", "phase1", AgentType.EXPLORE, required=False),
    AgentContract("Security Explore", "phase1", AgentType.GUARD),
    AgentContract("Recommend", "phase2", AgentType.EVALUATE),
    AgentContract("Fraud Score", "phase2", AgentType.EVALUATE),
    AgentContract("Inventory Check", "phase2", AgentType.EVALUATE),
    AgentContract("InterleavingController", "phase3", AgentType.PLAN),
    AgentContract("Policy Gate", "phase4", AgentType.GUARD),
]


def validate_phase_agents(phase: str, agents: Iterable[str] | None) -> Tuple[bool, List[str]]:
    allowed = set(AGENT_PHASES.get(phase, []))
    if not allowed:
        return True, []
    violations: List[str] = []
    for agent_name in list(agents or []):
        at = agent_type_for_name(agent_name)
        if at not in allowed:
            violations.append(f"{agent_name}:{at.value} not allowed in {phase}")
    return (len(violations) == 0, violations)


def deterministic_conflict_resolution(
    *,
    proposal: Dict[str, Any],
    policy: Dict[str, Any],
    security: Dict[str, Any] | None = None,
    fraud: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    sec = security or {}
    fr = fraud or {}
    pg = policy.get("policy_gate") if isinstance(policy.get("policy_gate"), dict) else {}
    verdict = str(pg.get("verdict") or "").lower()
    sec_sev = str(sec.get("severity") or "").lower()
    sec_risk = float(sec.get("risk_adj") or 0.0) if isinstance(sec, dict) else 0.0
    approval_required = bool(policy.get("approval_required", False)) or verdict == "escalate"
    block = verdict == "block" or sec_sev in ("critical",)

    try:
        fraud_score = float(fr.get("score") or 0.0)
    except Exception:
        fraud_score = 0.0
    try:
        fraud_threshold = float(os.getenv("FRAUD_REVIEW_THRESHOLD", "0.85") or 0.85)
    except Exception:
        fraud_threshold = 0.85

    reasons: List[str] = []
    if block:
        outcome = "block"
        reasons.append("hard_block_policy_or_security")
    elif approval_required or sec_sev in ("high",) or sec_risk >= 70 or fraud_score >= fraud_threshold:
        outcome = "review"
        reasons.append("manual_review_required")
    else:
        outcome = "allow"
        reasons.append("no_conflicting_high_risk_signals")

    synthesis = {
        "policy": "deterministic_conflict_v1",
        "outcome": outcome,
        "reasons": reasons,
        "signals": {
            "policy_verdict": verdict or None,
            "approval_required": bool(approval_required),
            "security_severity": sec_sev or None,
            "security_risk_adj": sec_risk,
            "fraud_score": fraud_score,
            "fraud_threshold": fraud_threshold,
            "auto_decision": (proposal.get("auto_decision") if isinstance(proposal, dict) else None),
        },
    }
    # Compute a simple numeric synthesis weight (0.0 - 1.0) to surface how strongly signals push towards review/block.
    try:
        policy_weight = 0.6 if verdict == "block" else (0.3 if verdict == "escalate" or verdict == "review" else 0.0)
    except Exception:
        policy_weight = 0.0
    try:
        security_weight = min(max(float(sec_risk or 0.0) / 100.0 * 0.4, 0.0), 0.4)
    except Exception:
        security_weight = 0.0
    try:
        fraud_weight = 0.0
        if fraud_threshold > 0:
            fraud_weight = min(max(fraud_score / float(fraud_threshold or 1.0) * 0.4, 0.0), 0.4)
    except Exception:
        fraud_weight = 0.0
    total_weight = min(policy_weight + security_weight + fraud_weight, 1.0)
    synthesis["weights"] = {
        "policy": round(policy_weight, 3),
        "security": round(security_weight, 3),
        "fraud": round(fraud_weight, 3),
        "total": round(float(total_weight), 3),
    }
    synthesis["synthesis_weight"] = float(total_weight)
    return synthesis


def apply_synthesis_to_policy(policy: Dict[str, Any], synthesis: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(policy or {})
    outcome = str(synthesis.get("outcome") or "")
    if outcome == "block":
        out["allowed"] = False
        out["approval_required"] = True
        out["deterministic_outcome"] = "block"
    elif outcome == "review":
        out["allowed"] = True
        out["approval_required"] = True
        out["deterministic_outcome"] = "review"
    elif outcome == "allow":
        out["allowed"] = True
        out["approval_required"] = False
        out["deterministic_outcome"] = "allow"
    return out
