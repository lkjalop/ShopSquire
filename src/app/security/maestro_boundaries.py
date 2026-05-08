"""MAESTRO Agent Security Boundary Framework.

Implements the MAESTRO framework for agentic AI security:
- Agent trust boundaries (what each agent can/cannot do)
- Tool misuse detection (agents calling tools outside their scope)
- Autonomous decision risk limits (max value, max impact per agent)
- Inter-agent communication boundaries (who can talk to whom)

Reference: MAESTRO Framework for Agentic AI Security (2025)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set
from src.app.services.registry import get_tool_metadata


# ---------------------------------------------------------------------------
# Enforcement mode
# ---------------------------------------------------------------------------
# MAESTRO_ENFORCEMENT_MODE controls what happens when a boundary violation is found:
#   "audit"  — log violations, never raise (default; forensics only)
#   "warn"   — log violations, emit a warning but continue
#   "block"  — raise MaestroViolationError for critical/high violations, blocking execution
#
# Set via environment variable. Defaults to "audit" so existing behaviour is unchanged.
_ENFORCEMENT_MODE: str = os.getenv("MAESTRO_ENFORCEMENT_MODE", "audit").strip().lower()
_BLOCK_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})


class MaestroViolationError(Exception):
    """Raised in 'block' enforcement mode when a critical/high boundary violation occurs.

    Callers (orchestrator, recommend ingress) should catch this and convert
    to HTTP 403 or equivalent policy-gate rejection.
    """
    def __init__(self, violations: List["BoundaryViolation"]) -> None:
        self.violations = violations
        top = violations[0] if violations else None
        detail = top.detail if top else "unknown violation"
        super().__init__(f"MAESTRO boundary violation [{top.severity if top else 'unknown'}]: {detail}")


# ---------------------------------------------------------------------------
# Agent boundary definitions
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AgentBoundary:
    """Security boundary spec for a single agent."""
    agent_name: str
    allowed_tools: FrozenSet[str] = frozenset()
    allowed_data_scopes: FrozenSet[str] = frozenset()  # e.g. "products", "orders", "pii"
    max_autonomous_value_usd: float = 0.0  # max $ value the agent can auto-approve
    can_write_db: bool = False
    can_call_external_api: bool = False
    can_invoke_llm: bool = False
    can_escalate: bool = True
    allowed_peers: FrozenSet[str] = frozenset()  # agents it can communicate with
    risk_tier: str = "low"  # "low", "medium", "high", "critical"


# Central registry of all agent boundaries
AGENT_BOUNDARIES: Dict[str, AgentBoundary] = {
    "NLP_Search_Agent": AgentBoundary(
        agent_name="NLP_Search_Agent",
        allowed_tools=frozenset(["parse_query", "extract_constraints", "merge_slots"]),
        allowed_data_scopes=frozenset(["products", "categories"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["Candidate_Retrieval_Agent", "NQE_Engine"]),
        risk_tier="low",
    ),
    "Candidate_Retrieval_Agent": AgentBoundary(
        agent_name="Candidate_Retrieval_Agent",
        allowed_tools=frozenset(["search_catalog", "filter_products", "semantic_search"]),
        allowed_data_scopes=frozenset(["products", "inventory"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["NLP_Search_Agent", "Product_Ranking_Agent"]),
        risk_tier="low",
    ),
    "Product_Ranking_Agent": AgentBoundary(
        agent_name="Product_Ranking_Agent",
        allowed_tools=frozenset(["rank_products", "compute_scores", "generate_why"]),
        allowed_data_scopes=frozenset(["products"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=True,
        allowed_peers=frozenset(["Candidate_Retrieval_Agent", "Debate_Coordinator"]),
        risk_tier="low",
    ),
    "NQE_Engine": AgentBoundary(
        agent_name="NQE_Engine",
        allowed_tools=frozenset(["propose_questions", "detect_context"]),
        allowed_data_scopes=frozenset(["products", "categories", "user_preferences"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["NLP_Search_Agent", "Use_Case_Advisor"]),
        risk_tier="low",
    ),
    "Fraud_Scoring_Agent": AgentBoundary(
        agent_name="Fraud_Scoring_Agent",
        allowed_tools=frozenset(["score_fraud", "check_phash", "graph_signals", "biometrics"]),
        allowed_data_scopes=frozenset(["orders", "sessions", "fraud_db"]),
        max_autonomous_value_usd=0.0,
        can_write_db=True,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["Security_Observer_Agent", "GNN_Fraud_Detector"]),
        risk_tier="medium",
    ),
    "CV_Label_Agent": AgentBoundary(
        agent_name="CV_Label_Agent",
        allowed_tools=frozenset(["classify_image", "extract_labels", "detect_damage"]),
        allowed_data_scopes=frozenset(["images", "products"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=True,
        allowed_peers=frozenset(["Product_Identity_Agent", "CV_Forensics_Agent"]),
        risk_tier="low",
    ),
    "Security_Observer_Agent": AgentBoundary(
        agent_name="Security_Observer_Agent",
        allowed_tools=frozenset(["analyze_payload", "detect_threats", "kev_check"]),
        allowed_data_scopes=frozenset(["sessions", "payloads", "security_events"]),
        max_autonomous_value_usd=0.0,
        can_write_db=True,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["Fraud_Scoring_Agent", "Escalation_Agent"]),
        risk_tier="high",
    ),
    "Orchestrator": AgentBoundary(
        agent_name="Orchestrator",
        allowed_tools=frozenset(["route_agents", "build_proposal", "execute_decision"]),
        allowed_data_scopes=frozenset(["products", "orders", "sessions", "payloads"]),
        max_autonomous_value_usd=500.0,
        can_write_db=True,
        can_call_external_api=True,
        can_invoke_llm=True,
        can_escalate=True,
        allowed_peers=frozenset([
            "NLP_Search_Agent", "Candidate_Retrieval_Agent", "Product_Ranking_Agent",
            "NQE_Engine", "Fraud_Scoring_Agent", "CV_Label_Agent",
            "Security_Observer_Agent", "Debate_Coordinator", "Post_LLM_Verifier",
        ]),
        risk_tier="critical",
    ),
    "Debate_Coordinator": AgentBoundary(
        agent_name="Debate_Coordinator",
        allowed_tools=frozenset(["run_debate", "score_risk"]),
        allowed_data_scopes=frozenset(["proposals", "evidence"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["Orchestrator", "Product_Ranking_Agent"]),
        risk_tier="medium",
    ),
    "Post_LLM_Verifier": AgentBoundary(
        agent_name="Post_LLM_Verifier",
        allowed_tools=frozenset(["verify_output", "check_hallucination", "check_secrets"]),
        allowed_data_scopes=frozenset(["llm_outputs"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["Orchestrator"]),
        risk_tier="medium",
    ),
    "Email_Security_Agent": AgentBoundary(
        agent_name="Email_Security_Agent",
        allowed_tools=frozenset(["validate_auth", "detect_bec", "detect_thread_hijack"]),
        allowed_data_scopes=frozenset(["emails", "headers"]),
        max_autonomous_value_usd=0.0,
        can_write_db=True,
        can_call_external_api=False,
        can_invoke_llm=True,
        allowed_peers=frozenset(["Security_Observer_Agent"]),
        risk_tier="high",
    ),
    "sender_auth_agent": AgentBoundary(
        agent_name="sender_auth_agent",
        allowed_tools=frozenset(["validate_auth", "analyze_headers", "score_reply_drift"]),
        allowed_data_scopes=frozenset(["headers", "emails"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["correlation_agent", "explanation_agent"]),
        risk_tier="medium",
    ),
    "attachment_forensics_agent": AgentBoundary(
        agent_name="attachment_forensics_agent",
        allowed_tools=frozenset(["extract_text", "ocr_attachment", "parse_pdf", "scan_qr", "extract_bank_fields"]),
        allowed_data_scopes=frozenset(["attachments", "payloads"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["baseline_agent", "correlation_agent", "explanation_agent"]),
        risk_tier="high",
    ),
    "baseline_agent": AgentBoundary(
        agent_name="baseline_agent",
        allowed_tools=frozenset(["compare_template_hashes", "compare_bank_fingerprints", "score_supplier_drift"]),
        allowed_data_scopes=frozenset(["suppliers", "attachments", "security_events"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["attachment_forensics_agent", "correlation_agent", "explanation_agent"]),
        risk_tier="medium",
    ),
    "correlation_agent": AgentBoundary(
        agent_name="correlation_agent",
        allowed_tools=frozenset(["link_related_incidents", "score_campaign_overlap", "build_incident_context"]),
        allowed_data_scopes=frozenset(["security_events", "emails", "suppliers"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["sender_auth_agent", "attachment_forensics_agent", "baseline_agent", "explanation_agent"]),
        risk_tier="medium",
    ),
    "explanation_agent": AgentBoundary(
        agent_name="explanation_agent",
        allowed_tools=frozenset(["summarize_findings", "map_policy_guidance", "render_explanations"]),
        allowed_data_scopes=frozenset(["security_events", "policies", "emails", "attachments"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=True,
        allowed_peers=frozenset(["sender_auth_agent", "attachment_forensics_agent", "baseline_agent", "correlation_agent", "playbook_agent"]),
        risk_tier="medium",
    ),
    "playbook_agent": AgentBoundary(
        agent_name="playbook_agent",
        allowed_tools=frozenset(["map_playbook_steps", "propose_gated_actions", "render_next_steps"]),
        allowed_data_scopes=frozenset(["security_events", "policies"]),
        max_autonomous_value_usd=0.0,
        can_write_db=False,
        can_call_external_api=False,
        can_invoke_llm=False,
        allowed_peers=frozenset(["explanation_agent"]),
        risk_tier="high",
    ),
    "ERP_EDI_Connector": AgentBoundary(
        agent_name="ERP_EDI_Connector",
        allowed_tools=frozenset(["get_supplier_signals", "parse_edi", "sync_inventory"]),
        allowed_data_scopes=frozenset(["orders", "suppliers", "inventory"]),
        max_autonomous_value_usd=0.0,
        can_write_db=True,
        can_call_external_api=True,
        can_invoke_llm=False,
        allowed_peers=frozenset(["Orchestrator"]),
        risk_tier="high",
    ),
}


# ---------------------------------------------------------------------------
# Boundary violation detection
# ---------------------------------------------------------------------------
@dataclass
class BoundaryViolation:
    agent_name: str
    violation_type: str  # "tool_misuse", "data_scope", "peer_violation", "value_exceeded"
    detail: str
    severity: str = "warning"


def check_tool_access(agent_name: str, tool_name: str) -> Optional[BoundaryViolation]:
    """Check if an agent is allowed to use a specific tool."""
    boundary = AGENT_BOUNDARIES.get(agent_name)
    if not boundary:
        return None  # unknown agent — no boundary defined
    if tool_name not in boundary.allowed_tools:
        meta = get_tool_metadata(tool_name)
        scoped_agents = meta.get("agent_types") if isinstance(meta.get("agent_types"), list) else []
        if scoped_agents and str(agent_name).strip().lower() in [str(x).strip().lower() for x in scoped_agents]:
            return None
        return BoundaryViolation(
            agent_name=agent_name,
            violation_type="tool_misuse",
            detail=f"Agent '{agent_name}' attempted to use tool '{tool_name}' outside its boundary. Allowed: {sorted(boundary.allowed_tools)}",
            severity="high" if boundary.risk_tier in ("high", "critical") else "warning",
        )
    return None


def check_data_scope(agent_name: str, data_scope: str) -> Optional[BoundaryViolation]:
    """Check if an agent is allowed to access a data scope."""
    boundary = AGENT_BOUNDARIES.get(agent_name)
    if not boundary:
        return None
    if data_scope not in boundary.allowed_data_scopes:
        return BoundaryViolation(
            agent_name=agent_name,
            violation_type="data_scope",
            detail=f"Agent '{agent_name}' tried to access '{data_scope}'. Allowed: {sorted(boundary.allowed_data_scopes)}",
            severity="high" if "pii" in data_scope else "warning",
        )
    return None


def check_peer_communication(from_agent: str, to_agent: str) -> Optional[BoundaryViolation]:
    """Check if inter-agent communication is allowed."""
    boundary = AGENT_BOUNDARIES.get(from_agent)
    if not boundary:
        return None
    if to_agent not in boundary.allowed_peers:
        return BoundaryViolation(
            agent_name=from_agent,
            violation_type="peer_violation",
            detail=f"Agent '{from_agent}' attempted to invoke '{to_agent}'. Allowed peers: {sorted(boundary.allowed_peers)}",
            severity="high",
        )
    return None


def check_autonomous_value(agent_name: str, value_usd: float) -> Optional[BoundaryViolation]:
    """Check if an agent's autonomous decision exceeds its value limit."""
    boundary = AGENT_BOUNDARIES.get(agent_name)
    if not boundary:
        return None
    if value_usd > boundary.max_autonomous_value_usd:
        return BoundaryViolation(
            agent_name=agent_name,
            violation_type="value_exceeded",
            detail=f"Agent '{agent_name}' tried to auto-approve ${value_usd:.2f} (limit: ${boundary.max_autonomous_value_usd:.2f})",
            severity="critical",
        )
    return None


def validate_agent_action(
    *,
    agent_name: str,
    tool_name: Optional[str] = None,
    data_scope: Optional[str] = None,
    target_agent: Optional[str] = None,
    value_usd: float = 0.0,
) -> List[BoundaryViolation]:
    """Run all boundary checks for a single agent action.

    Returns a list of violations (empty = action is within boundaries).
    An agent not present in AGENT_BOUNDARIES produces a ``missing_boundary``
    violation — this is deliberate: an unregistered agent has no defined
    scope, which is itself a boundary violation rather than a clean pass.
    """
    violations: List[BoundaryViolation] = []
    if agent_name not in AGENT_BOUNDARIES:
        violations.append(BoundaryViolation(
            agent_name=agent_name,
            violation_type="missing_boundary",
            detail=(
                f"Agent '{agent_name}' has no registered MAESTRO boundary. "
                "Unregistered agents must be added to AGENT_BOUNDARIES before deployment."
            ),
            severity="warning",
        ))
        return violations
    if tool_name:
        v = check_tool_access(agent_name, tool_name)
        if v:
            violations.append(v)
    if data_scope:
        v = check_data_scope(agent_name, data_scope)
        if v:
            violations.append(v)
    if target_agent:
        v = check_peer_communication(agent_name, target_agent)
        if v:
            violations.append(v)
    if value_usd > 0:
        v = check_autonomous_value(agent_name, value_usd)
        if v:
            violations.append(v)

    # Enforcement gate — applies AFTER all checks so callers always get the full list.
    if violations and _ENFORCEMENT_MODE == "block":
        blocking = [v for v in violations if v.severity in _BLOCK_SEVERITIES]
        if blocking:
            raise MaestroViolationError(blocking)

    return violations


def get_boundary_summary() -> Dict[str, Any]:
    """Return a summary of all agent boundaries for documentation/audit."""
    summary = {}
    for name, b in AGENT_BOUNDARIES.items():
        summary[name] = {
            "risk_tier": b.risk_tier,
            "allowed_tools": sorted(b.allowed_tools),
            "allowed_data_scopes": sorted(b.allowed_data_scopes),
            "max_autonomous_value_usd": b.max_autonomous_value_usd,
            "can_write_db": b.can_write_db,
            "can_call_external_api": b.can_call_external_api,
            "can_invoke_llm": b.can_invoke_llm,
            "allowed_peers": sorted(b.allowed_peers),
        }
    return summary
