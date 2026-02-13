from __future__ import annotations

from enum import Enum
from typing import Dict, List


class AgentType(str, Enum):
    """Typed agent specializations used for orchestration and trace tagging."""

    EXPLORE = "explore"
    EVALUATE = "evaluate"
    ACTION = "action"
    PLAN = "plan"
    GUARD = "guard"


AGENT_PHASES: Dict[str, List[AgentType]] = {
    "phase1": [AgentType.EXPLORE, AgentType.GUARD],
    "phase2": [AgentType.EVALUATE],
    "phase3": [AgentType.PLAN],
    "phase4": [AgentType.ACTION, AgentType.GUARD],
}


def agent_type_for_name(name: str) -> AgentType:
    n = (name or "").lower()
    if any(k in n for k in ("nlp", "cv", "security", "observer")):
        return AgentType.EXPLORE
    if any(k in n for k in ("recommend", "fraud", "inventory", "rerank")):
        return AgentType.EVALUATE
    if any(k in n for k in ("ticket", "incident", "payment", "execute")):
        return AgentType.ACTION
    if any(k in n for k in ("plan", "orchestrator")):
        return AgentType.PLAN
    if any(k in n for k in ("policy", "gate", "firewall")):
        return AgentType.GUARD
    return AgentType.EXPLORE
