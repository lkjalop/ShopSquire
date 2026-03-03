from __future__ import annotations

from typing import Any, Dict, List


def _confidence_from_signals(signals: Dict[str, Any]) -> float:
    score = 0.0
    for k, v in (signals or {}).items():
        try:
            fv = float(v)
            if fv > 0:
                score += min(1.0, fv)
        except Exception:
            if bool(v):
                score += 0.5
    return min(0.99, max(0.05, score / max(1.0, float(len(signals or {})))))


def run_structured_debate(
    *,
    scenario: str,
    proposal: Dict[str, Any],
    evidence: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    ev = evidence if isinstance(evidence, dict) else {}
    sc = str(scenario or "general").strip().lower()
    reasons: List[str] = []
    risks: List[str] = []
    mitigations: List[str] = []

    if sc in ("supplier_change", "supplier_changes"):
        if bool(ev.get("domain_age_days") is not None and float(ev.get("domain_age_days") or 0.0) < 45):
            risks.append("new_supplier_domain")
        if bool(ev.get("bank_account_changed")):
            risks.append("bank_change_without_callback")
        mitigations.extend(["out_of_band_supplier_callback", "hold_payment_until_verified"])
    elif sc in ("policy_update", "policy_updates"):
        if bool(ev.get("policy_version_mismatch")):
            risks.append("policy_version_mismatch")
        if bool(ev.get("missing_approval")):
            risks.append("policy_update_without_approval")
        mitigations.extend(["require_dual_approval", "apply_latest_policy_snapshot"])
    elif sc in ("cv_ambiguity", "cv"):
        if bool(ev.get("ocr_confidence") is not None and float(ev.get("ocr_confidence") or 0.0) < 0.75):
            risks.append("ocr_low_confidence")
        if bool(ev.get("gan_fake_image_suspected")):
            risks.append("possible_synthetic_image")
        mitigations.extend(["human_review_required", "request_source_document"])
    elif sc in ("impossible_travel", "asn_geoip"):
        if bool(ev.get("velocity_kmh") is not None and float(ev.get("velocity_kmh") or 0.0) > 900.0):
            risks.append("impossible_travel_velocity")
        if bool(ev.get("asn_risk") is not None and float(ev.get("asn_risk") or 0.0) > 0.7):
            risks.append("high_risk_asn")
        mitigations.extend(["step_up_mfa", "session_challenge", "geoip_reverification"])
    elif sc in ("multi_channel_attack", "cross_channel"):
        if bool(ev.get("shared_trace_id")):
            risks.append("cross_channel_correlation_match")
        if bool(ev.get("supplier_identity_mismatch")):
            risks.append("supplier_identity_mismatch")
        mitigations.extend(["freeze_payment_change", "ticket_escalation", "oob_callback"])
    elif sc in ("model_poisoning",):
        if bool(ev.get("label_source_untrusted")):
            risks.append("untrusted_label_source")
        if bool(ev.get("adversarial_sample_spike")):
            risks.append("adversarial_sample_spike")
        mitigations.extend(["quarantine_training_batch", "trust_weighted_retrain", "require_model_card_approval"])
    elif sc in ("legal_forgery", "authority_abuse"):
        if bool(ev.get("signer_mismatch")):
            risks.append("signer_identity_mismatch")
        if bool(ev.get("authority_language_pressure")):
            risks.append("authority_language_abuse")
        mitigations.extend(["legal_hold_review", "issuer_domain_validation"])
    elif sc in ("supply_chain_cascading",):
        if bool(ev.get("sbom_drift")):
            risks.append("sbom_drift_detected")
        if bool(ev.get("artifact_signature_invalid")):
            risks.append("artifact_signature_invalid")
        mitigations.extend(["block_deploy", "dependency_rollback", "egress_guard"])
    elif sc in ("insider_external_combo",):
        if bool(ev.get("privilege_spike")):
            risks.append("privilege_spike")
        if bool(ev.get("bec_linked")):
            risks.append("bec_linked_to_employee_account")
        mitigations.extend(["force_session_reauth", "isolate_account", "mandatory_human_approval"])

    # ── Recommendation debate scenarios ──
    elif sc in ("product_comparison", "product_debate"):
        product_a_score = float(ev.get("product_a_score") or 0)
        product_b_score = float(ev.get("product_b_score") or 0)
        score_delta = abs(product_a_score - product_b_score)
        if score_delta < 0.05:
            risks.append("scores_too_close_to_differentiate")
        if bool(ev.get("user_stated_preference_conflict")):
            risks.append("user_preference_contradicts_score")
        if bool(ev.get("missing_key_spec")):
            risks.append("missing_spec_data_for_comparison")
        mitigations.extend(["show_detailed_comparison", "highlight_key_differences", "ask_tiebreaker_question"])

    elif sc in ("budget_tradeoff", "price_quality"):
        budget_max = float(ev.get("budget_max") or 0)
        recommended_price = float(ev.get("recommended_price") or 0)
        if recommended_price > budget_max * 1.15:
            risks.append("recommendation_over_budget")
        if recommended_price < budget_max * 0.5:
            risks.append("significant_underutilization_of_budget")
        if bool(ev.get("quality_compromise")):
            risks.append("quality_compromise_for_price")
        mitigations.extend(["present_budget_alternatives", "explain_value_proposition", "offer_tiered_options"])

    elif sc in ("use_case_fit", "use_case_mismatch"):
        fit_score = float(ev.get("use_case_fit_score") or 0)
        if fit_score < 0.6:
            risks.append("poor_use_case_fit")
        if bool(ev.get("overkill_specs")):
            risks.append("overkill_specs_for_use_case")
        if bool(ev.get("underpowered_for_use_case")):
            risks.append("underpowered_for_use_case")
        mitigations.extend(["suggest_better_fit_product", "explain_spec_requirements", "ask_use_case_clarification"])

    elif sc in ("brand_preference_conflict", "brand_debate"):
        if bool(ev.get("preferred_brand_unavailable")):
            risks.append("preferred_brand_not_in_stock")
        if bool(ev.get("preferred_brand_poor_value")):
            risks.append("preferred_brand_poor_value_for_specs")
        if bool(ev.get("brand_bias_detected")):
            risks.append("potential_brand_bias_in_ranking")
        mitigations.extend(["present_cross_brand_comparison", "explain_brand_tradeoffs", "respect_user_preference"])

    elif sc in ("returning_customer_conflict",):
        if bool(ev.get("profile_stale")):
            risks.append("user_profile_may_be_outdated")
        if bool(ev.get("preference_changed")):
            risks.append("current_query_contradicts_profile")
        mitigations.extend(["ask_confirmation_of_preferences", "weight_current_session_higher"])

    else:
        if bool(ev.get("high_risk")):
            risks.append("high_risk_signal")
        mitigations.append("manual_review")

    prop_action = str((proposal or {}).get("action") or "review")
    if prop_action in ("allow", "auto_resolve") and risks:
        reasons.append("proposal_too_permissive_for_risk_signals")
    if prop_action in ("block", "deny") and not risks:
        reasons.append("proposal_may_be_overblocking")

    confidence = _confidence_from_signals(ev)
    risk_severity_score = min(1.0, max(0.0, float(len(risks)) / 5.0))
    quality_feedback = {
        "outcome_quality": float(ev.get("outcome_quality") or 0.0) if str(ev.get("outcome_quality") or "").strip() else None,
        "reviewer_disagreement_rate": float(ev.get("reviewer_disagreement_rate") or 0.0) if str(ev.get("reviewer_disagreement_rate") or "").strip() else None,
    }
    judge_decision = "uphold"
    if reasons:
        judge_decision = "revise"
    if risks and prop_action in ("allow", "auto_resolve"):
        judge_decision = "escalate"
    if risk_severity_score >= 0.8 and prop_action not in ("block", "deny"):
        judge_decision = "escalate"

    return {
        "scenario": sc,
        "proposer": {"proposal": proposal or {}, "confidence": confidence},
        "challenger": {
            "risks": risks,
            "reasons": reasons,
            "mitigations": mitigations,
        },
        "judge": {
            "decision": judge_decision,
            "recommended_action": ("review" if judge_decision in ("revise", "escalate") else prop_action),
            "confidence": max(0.05, min(0.99, 1.0 - (0.15 * len(reasons)))),
            "risk_severity_score": round(risk_severity_score, 4),
        },
        "quality_feedback": quality_feedback,
    }
