from __future__ import annotations

from typing import Tuple


CANONICAL_TRACE_EVENTS = {
    "security_scan",
    "intent_classify",
    "constraint_parse",
    "candidate_retrieve",
    "candidate_rerank",
    "cv_analysis",
    "fraud_score",
    "inventory_check",
    "tier_decision",
    "policy_verdict",
    "policy_gate",
    "ab_assignment",
    "proposal_build",
    "execution_result",
    "feedback_loop",
    "reward_signal",
    "ticket_created",
    "agent_invocation",
    "phase_started",
    "phase_completed",
    "synthesis_reasoning",
    "tool_budget",
    "interleaving_event",
    "interleaving_summary",
    "fraud_isolation_forest",
    "cv_tags",
    "db_down_test",
    "flood",
    # Added for test alignment and agent handoff semantics
    "handoff_requested",
    "test_event",
    "nqe_plan_built",
    "nqe_question_shown",
    "nqe_assumption_applied",
    "nqe_fallback_alternatives",
    "nqe_user_answer_bound",
    "upsell_promotion_selected",
    "shortlist_memory_lock",
    "turn_envelope_diff",
    "intent_decomposed",
    "template_selected",
    "answer_coverage_scored",
    "copywriting",
    "copy_policy_gate",
    # Evidence-led shopping-case events must remain explicit. Collapsing these
    # into ``feedback_loop`` makes an execution/audit state look like generic
    # conversational follow-up in Decision Trace.
    "ambiguity_exploration_projected",
    "buyer_requirement_proposal_accepted",
    "shopping_case_obligations_retained",
}


_ALIASES = {
    "phase_start": "phase_started",
    "phase_complete": "phase_completed",
    "cv_playbook": "proposal_build",
    "auto_cv_decision": "execution_result",
    "intent_classified": "intent_classify",
    "candidate_retrieval": "candidate_retrieve",
    "rerank": "candidate_rerank",
    "model_selection": "tier_decision",
    "recommend_request": "proposal_build",
    "recommendation": "proposal_build",
    "security_watch": "security_scan",
    "trust_routing": "policy_verdict",
    "risk_summary": "fraud_score",
    "cv_analyze": "cv_analysis",
    "evidence_bundle": "execution_result",
    "evidence_persisted": "execution_result",
    "cv_pipeline": "execution_result",
    "human_escalation": "execution_result",
    "next_questions": "feedback_loop",
    "reward_signal": "feedback_loop",
    "contract_nlp_analysis": "constraint_parse",
    "nlp_quality_gate": "policy_verdict",
    "agent_process": "proposal_build",
    "user_query": "intent_classify",
    "llm_error": "execution_result",
    "tool_call": "execution_result",
    "voice_commit": "execution_result",
    "orchestrate": "proposal_build",
    "incidentroute": "execution_result",
}


def normalize_trace_event_type(event_type: str | None) -> Tuple[str, str | None]:
    raw = str(event_type or "").strip().lower()
    if not raw:
        return ("execution_result", None)
    mapped = _ALIASES.get(raw, raw)
    if mapped in CANONICAL_TRACE_EVENTS:
        return (mapped, None)
    return ("feedback_loop", raw)
