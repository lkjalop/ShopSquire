"""Clarify-turn payload builders (agnostic CORE), extracted from suggest()'s early-return block.

Two payload shapes when the turn ends WITHOUT retrieval:
  * support-claim  — post-purchase support routing (cards + playbooks);
  * NQE clarify    — ask 1-2 narrowing questions before running the catalog.

Pure builders over explicit inputs. The support-claim COPY (intro line, card titles, playbook
steps, agent names) is vertical flavour read from the active profile's ``support_playbooks`` slot;
core carries only a vertical-NEUTRAL default so a profile without the slot still answers honestly.
No product vocabulary in this module — it lives in the profile JSON.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Vertical-neutral default: used when a profile carries no ``support_playbooks`` slot. Deliberately
# generic ("item", not "device") so it is honest in ANY store; electronics.json overrides it with
# device-specific copy.
_DEFAULT_SUPPORT_PLAYBOOK: Dict[str, Any] = {
    "default_issue": "order_issue",
    "intro": "It looks like you need help with an order or item. I can help with returns, "
             "replacements, or warranty/coverage steps.",
    "intro_found_suffix": "I found account order history to review next.",
    "intro_unknown_suffix": "Share a receipt or order reference if you have one.",
    "summary_template": "Support flow active for {issue}.",
    "cards": [
        {"id": "coverage_status", "title": "Coverage / Warranty", "status_from": "warranty",
         "message": "Sign in and provide order details to verify coverage."},
        {"id": "resolution_path", "title": "Return / Replace Path", "status": "review",
         "message": "Provide order details and any photos so we can determine the best resolution."},
    ],
    "faq_playbooks": [
        {"id": "faq_general_claim", "title": "Order/item claims",
         "steps": ["Describe the issue", "Attach any photos", "Attach receipt or order reference"]},
    ],
    "parallel_agents": ["Support_Routing_Agent", "Warranty_Agent", "Support_Playbook_Agent"],
}


def _support_playbook() -> Dict[str, Any]:
    try:
        from src.app.platform.store_profile import profile_slot
        slot = profile_slot("support_playbooks", default=None)
        if isinstance(slot, dict) and slot:
            return {**_DEFAULT_SUPPORT_PLAYBOOK, **slot}
    except Exception:
        pass
    return _DEFAULT_SUPPORT_PLAYBOOK


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
    pb = _support_playbook()
    issue = str(constraints.get("issue_type") or pb["default_issue"]).strip().lower() or pb["default_issue"]
    warranty_found = str(warranty.get("status") or "").strip().lower() == "found"
    # Cards from the playbook; a card with status_from='warranty' binds the live warranty result.
    support_cards: List[Dict[str, Any]] = []
    for card in pb.get("cards") or []:
        c = {k: v for k, v in card.items() if k != "status_from"}
        if card.get("status_from") == "warranty":
            c["status"] = warranty.get("status") or "unknown"
            c["message"] = warranty.get("message") or card.get("message")
            c["order_ref"] = warranty.get("order_ref")
        support_cards.append(c)
    payload: Dict[str, Any] = {
        "results": [],
        "proposal": {"decision_mode": "support", "ranked_skus": []},
        "constraints_used": constraints,
        "followup_contract": followup_contract,
        "intent_execution_plan": intent_execution_plan,
        "policy_version": policy_version,
        "assistant_message": (
            str(pb["intro"]) + " "
            + (str(pb["intro_found_suffix"]) if warranty_found else str(pb["intro_unknown_suffix"]))
        ),
        "right_panel": {
            "mode": "support",
            "show_tiers": False,
            "summary": str(pb["summary_template"]).format(issue=(issue or "").replace("_", " ")),
            "image_untrusted": bool(image_reupload_reasons),
            "image_degraded_mode": bool(image_reupload_reasons),
            "security_route": "visual_sanitized" if image_reupload_reasons else "allow",
            "security_summary": (
                "Image flagged; using text-only fallback until a clean product photo is uploaded."
                if image_reupload_reasons
                else None
            ),
            "support_cards": support_cards,
            "faq_playbooks": pb.get("faq_playbooks") or [],
            "parallel_agents": pb.get("parallel_agents") or [],
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
