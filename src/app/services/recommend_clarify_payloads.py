"""Clarify-turn payload builders, extracted from suggest()'s early-return block.

Two payload shapes when the turn ends WITHOUT retrieval:
  * support-claim  — post-purchase damage/warranty routing (support cards + playbooks);
  * NQE clarify    — ask 1-2 narrowing questions before running the catalog.

Pure builders over explicit inputs (no closure reads, no I/O) so the shapes are testable and
suggest() sheds ~120 lines of dict literal. NOT registered in _CORE_MODULES yet: the support
copy ("damaged device", playbook steps) is vertical flavour that belongs in a future profile
``support_playbooks`` slot — extraction first, vocabulary migration when that slot lands.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _common_tail(*, question_plan: Dict[str, Any], view_hint: Dict[str, Any],
                 strategy_corr: Dict[str, Any], llm_model: Any, model_tier: Any,
                 complexity_signals: Any, nqe_selection_applied: Any, turn_type: Any,
                 referents: Any, memory_confidence: float) -> Dict[str, Any]:
    return {
        "question_plan": question_plan,
        "confidence_band": question_plan.get("confidence_band"),
        "ambiguity_reason": question_plan.get("ambiguity_reason"),
        "view_mode": view_hint.get("view_mode"),
        "view_reason": view_hint.get("view_reason"),
        "trace_tags": strategy_corr.get("tags") or [],
        "drilldown_hidden_tags": strategy_corr.get("hidden") or {},
        "llm_model": llm_model,
        "model_tier": model_tier,
        "complexity_signals": complexity_signals,
        "nqe_selection_applied": nqe_selection_applied,
        "turn_type": turn_type,
        "referents": referents,
        "memory_confidence": round(float(memory_confidence), 4),
    }


def build_support_clarify_payload(
    *,
    constraints: Dict[str, Any],
    followup_contract: Any,
    intent_execution_plan: Any,
    policy_version: Any,
    warranty: Dict[str, Any],
    image_reupload_reasons: Any,
    question_plan: Dict[str, Any],
    view_hint: Dict[str, Any],
    strategy_corr: Dict[str, Any],
    llm_model: Any,
    model_tier: Any,
    complexity_signals: Any,
    nqe_selection_applied: Any,
    turn_type: Any,
    referents: Any,
    memory_confidence: float,
) -> Dict[str, Any]:
    issue = str(constraints.get("issue_type") or "device_issue").strip().lower() or "device_issue"
    payload: Dict[str, Any] = {
        "results": [],
        "proposal": {"decision_mode": "support", "ranked_skus": []},
        "constraints_used": constraints,
        "followup_contract": followup_contract,
        "intent_execution_plan": intent_execution_plan,
        "policy_version": policy_version,
        "assistant_message": (
            "This looks like a damaged device. I can help with repair, warranty, or return steps. "
            + (
                "I found account order history to review next."
                if str(warranty.get("status") or "").strip().lower() == "found"
                else "Upload a receipt or order reference if you have one."
            )
        ),
        "right_panel": {
            "mode": "support",
            "show_tiers": False,
            "summary": f"Support flow active for {(issue or 'device issue').replace('_', ' ')}.",
            "image_untrusted": bool(image_reupload_reasons),
            "image_degraded_mode": bool(image_reupload_reasons),
            "security_route": "visual_sanitized" if image_reupload_reasons else "allow",
            "security_summary": (
                "Image flagged; using text-only fallback until a clean product photo is uploaded."
                if image_reupload_reasons
                else None
            ),
            "support_cards": [
                {
                    "id": "warranty_status",
                    "title": "Warranty/Coverage",
                    "status": warranty.get("status") or "unknown",
                    "message": warranty.get("message") or "Sign in and provide order details to verify coverage.",
                    "order_ref": warranty.get("order_ref"),
                },
                {
                    "id": "repair_return",
                    "title": "Repair / Return Path",
                    "status": "review",
                    "message": "Upload clear device and receipt photos to determine repair, return, or in-store diagnostics.",
                },
            ],
            "faq_playbooks": [
                {
                    "id": "faq_cracked_screen",
                    "title": "Physical damage claims",
                    "steps": ["Capture damage close-up", "Capture serial/label", "Attach receipt or order reference"],
                },
            ],
            "parallel_agents": [
                "CV_Triage_Agent",
                "Warranty_Agent",
                "Support_Playbook_Agent",
            ],
        },
        "next_questions": [],
        "needs_disambiguation": False,
        "agent_chain": [
            {"agent": "Support_Routing_Agent", "confidence": 0.94, "duration_ms": None},
        ],
    }
    payload.update(_common_tail(question_plan=question_plan, view_hint=view_hint,
                                strategy_corr=strategy_corr, llm_model=llm_model,
                                model_tier=model_tier, complexity_signals=complexity_signals,
                                nqe_selection_applied=nqe_selection_applied, turn_type=turn_type,
                                referents=referents, memory_confidence=memory_confidence))
    return payload


def build_nqe_clarify_payload(
    *,
    constraints: Dict[str, Any],
    followup_contract: Any,
    intent_execution_plan: Any,
    policy_version: Any,
    qty_refusal_note: Optional[str],
    next_questions: List[Any],
    needs_disambiguation: bool,
    question_plan: Dict[str, Any],
    view_hint: Dict[str, Any],
    strategy_corr: Dict[str, Any],
    llm_model: Any,
    model_tier: Any,
    complexity_signals: Any,
    nqe_selection_applied: Any,
    turn_type: Any,
    referents: Any,
    memory_confidence: float,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "results": [],
        "proposal": {"decision_mode": "rules", "ranked_skus": []},
        "constraints_used": constraints,
        "followup_contract": followup_contract,
        "intent_execution_plan": intent_execution_plan,
        "policy_version": policy_version,
        # the honest qty refusal (99999/0/negative — set at the early parse) must survive THIS
        # early-return payload too, not just the main narration path.
        "refusal_note": qty_refusal_note,
        "assistant_message": (
            (f"{qty_refusal_note}\n\n" if qty_refusal_note else "")
            + "I can narrow this quickly with one or two details. "
            "If you skip details, I'll assume sensible defaults and show constrained alternatives."
        ),
        "next_questions": next_questions,
        "needs_disambiguation": needs_disambiguation,
        "agent_chain": [
            {"agent": "NQE_Agent", "confidence": None, "duration_ms": None},
        ],
    }
    payload.update(_common_tail(question_plan=question_plan, view_hint=view_hint,
                                strategy_corr=strategy_corr, llm_model=llm_model,
                                model_tier=model_tier, complexity_signals=complexity_signals,
                                nqe_selection_applied=nqe_selection_applied, turn_type=turn_type,
                                referents=referents, memory_confidence=memory_confidence))
    return payload
