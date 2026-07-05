"""Action policy — canonical action names + policy build + playbook enforcement (extracted from
email_security.py, session 5).

Maps the verdict's ranked findings to a bounded, enforceable action policy (what the platform is
allowed to auto-do vs escalate). Pure over finding dicts; self-contained (nested predicate helper,
no external module deps). Never raises. Vertical-blind.
"""
from __future__ import annotations

from typing import Any, Dict, List  # noqa: F401

from src.app.security.email_findings import _finding_rank_score


def _canonical_action_name(action_type: str | None) -> str:
    action = str(action_type or "").strip().lower()
    mapping = {
        "create_ticket": "create_ticket",
        "create_incident": "create_ticket",
        "escalate_ticket": "create_ticket",
        "notify_ops": "notify_analyst",
        "notify_stakeholders": "notify_analyst",
        "send_message": "notify_analyst",
        "send_email": "notify_analyst",
        "send_notification_email": "notify_analyst",
        "email": "notify_analyst",
        "quarantine_email": "quarantine_email",
        "block_sender": "push_block_rule",
        "session_revoke": "suspend_user",
        "step_up_auth": "force_reauth",
        "hold_payment": "approve_payment_change",
        "apply_compensation": "approve_payment_change",
        "offer_discount": "approve_payment_change",
    }
    return mapping.get(action, action or "unknown")


def _build_action_policy(
    *,
    verdict: Dict[str, Any],
    structured_findings: list[dict[str, Any]],
    evidence_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    findings = [f for f in structured_findings if isinstance(f, dict)]
    ranked = sorted(findings, key=_finding_rank_score, reverse=True)
    route = str(verdict.get("route") or "auto_resolve")
    severity = str(verdict.get("severity") or "info")
    auth = evidence_snapshot.get("auth") if isinstance(evidence_snapshot.get("auth"), dict) else {}
    infra = evidence_snapshot.get("sender_infrastructure") if isinstance(evidence_snapshot.get("sender_infrastructure"), dict) else {}
    trust_case = evidence_snapshot.get("trust_case") if isinstance(evidence_snapshot.get("trust_case"), dict) else {}
    governance = evidence_snapshot.get("supplier_governance") if isinstance(evidence_snapshot.get("supplier_governance"), dict) else {}

    def _has(predicate) -> bool:
        return any(predicate(f) for f in ranked)

    has_direct_payment = _has(lambda f: str(f.get("finding_type") or "") == "payment_change_request" and str(f.get("evidence_kind") or "") == "direct")
    has_baseline_mismatch = _has(lambda f: str(f.get("finding_type") or "") in {"baseline_mismatch", "attachment_visual_drift"} or str(f.get("finding_category") or "") == "baseline_drift")
    has_auth_failure = bool(auth.get("dmarc_fail")) or _has(lambda f: str(f.get("finding_type") or "") in {"auth_failure", "reply_drift"})
    has_known_bad_infra = _has(lambda f: str(f.get("finding_type") or "") == "infrastructure_anomaly") or bool(((infra.get("reputation") if isinstance(infra.get("reputation"), dict) else {}) or {}).get("known_bad"))
    has_conflicting_evidence = _has(lambda f: str(f.get("finding_category") or "") == "contextual_supplier_mismatch") and not (has_direct_payment or has_auth_failure)
    pending_updates = [str(x or "") for x in (governance.get("pending_updates") or []) if str(x or "").strip()]
    has_pending_bank_review = any(x.startswith("review_bank_fingerprint:") for x in pending_updates)
    has_pending_domain_review = any(x.startswith("review_domain:") for x in pending_updates)
    has_pending_template_review = any(x.startswith("review_template_hash:") for x in pending_updates)
    highest_conf = max((float(f.get("confidence_score") or 0.0) for f in ranked), default=0.0)
    high_business_impact = bool(has_direct_payment or has_baseline_mismatch or has_known_bad_infra or severity == "error" or has_pending_bank_review)
    trusted_sender = not has_auth_failure and str(trust_case.get("level") or "").lower() in {"trusted", "medium"} and not bool(infra.get("reply_domain_mismatch"))

    lane = "lane_1_auto_allow"
    lane_reason = "The sender and attachments look consistent with a normal supplier workflow and no payment-diversion indicators were found."
    if route == "security_review" or has_direct_payment or (has_auth_failure and has_baseline_mismatch) or has_known_bad_infra:
        lane = "lane_2_auto_escalate"
        lane_reason = "High-confidence fraud or sender-trust controls were triggered, so the platform escalated immediately while preserving evidence."
    elif route == "human_review" or has_conflicting_evidence or has_pending_bank_review or has_pending_domain_review or has_pending_template_review or (high_business_impact and 0.45 <= highest_conf < 0.85):
        lane = "lane_3_human_gate"
        lane_reason = "The message has meaningful business risk or conflicting evidence, so a human must approve the final sensitive action."
    elif trusted_sender and not has_direct_payment and not has_baseline_mismatch:
        lane = "lane_1_auto_allow"

    auto_allowed = {"notify_analyst", "create_ticket", "security_review", "passive_siem_event"}
    human_required = {"approve_supplier_update", "approve_payment_change", "mark_sender_trusted", "push_block_rule", "suspend_user"}
    blocked = {"open_internet", "access_secrets"}
    if lane == "lane_1_auto_allow":
        auto_allowed.add("approve_supplier_update")
        human_required.discard("approve_supplier_update")
    if lane == "lane_2_auto_escalate":
        auto_allowed.update({"quarantine_email", "force_reauth"})
    if lane == "lane_3_human_gate":
        auto_allowed.add("quarantine_email")

    threshold_reasons: list[str] = []
    if has_direct_payment:
        threshold_reasons.append("Direct payment-change evidence was extracted from the attachment.")
    if has_auth_failure:
        threshold_reasons.append("Sender identity or reply-chain controls failed.")
    if has_baseline_mismatch:
        threshold_reasons.append("The document drifted from the trusted supplier baseline.")
    if has_known_bad_infra:
        threshold_reasons.append("Sender infrastructure or related incident overlap increased confidence this is hostile.")
    if has_conflicting_evidence:
        threshold_reasons.append("Some evidence is suspicious but not conclusive enough for unsupervised business action.")
    if has_pending_bank_review:
        threshold_reasons.append("A newly observed bank fingerprint still requires supplier-governance approval.")
    if has_pending_domain_review:
        threshold_reasons.append("A newly observed sender or supplier domain still requires supplier-governance approval.")
    if has_pending_template_review:
        threshold_reasons.append("A newly observed supplier template hash still requires governance review before trust can be extended.")
    if not threshold_reasons:
        threshold_reasons.append(lane_reason)

    return {
        "lane": lane,
        "lane_label": lane.replace("_", " "),
        "lane_reason": lane_reason,
        "auto_allowed_actions": sorted(auto_allowed),
        "human_approval_actions": sorted(human_required),
        "blocked_actions": sorted(blocked),
        "threshold_reasons": threshold_reasons[:6],
        "top_business_reasons": [
            str(f.get("business_meaning") or f.get("summary") or "").strip()
            for f in ranked[:3]
            if str(f.get("business_meaning") or f.get("summary") or "").strip()
        ][:3],
        "metrics": {
            "highest_finding_confidence": round(highest_conf, 4),
            "direct_payment_change": has_direct_payment,
            "baseline_mismatch": has_baseline_mismatch,
            "sender_auth_failure": has_auth_failure,
            "known_bad_infrastructure": has_known_bad_infra,
            "conflicting_evidence": has_conflicting_evidence,
            "pending_bank_review": has_pending_bank_review,
            "pending_domain_review": has_pending_domain_review,
            "pending_template_review": has_pending_template_review,
            "high_business_impact": high_business_impact,
        },
        "human_gate": {
            "required": lane == "lane_3_human_gate",
            "approval_scope": "sensitive_business_actions" if lane == "lane_3_human_gate" else "none",
            "business_hold_message": (
                "Hold payment changes and verify supplier details out of band before any sensitive action."
                if lane in {"lane_2_auto_escalate", "lane_3_human_gate"}
                else "Normal processing may continue because no high-risk supplier-fraud indicators were found."
            ),
            "sensitive_actions": [
                "approve_supplier_update",
                "approve_payment_change",
                "mark_sender_trusted",
                "push_block_rule",
                "suspend_user",
            ],
        },
    }


def _enforce_playbook_actions(
    *,
    actions: list[dict[str, Any]],
    action_policy: Dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    filtered: list[dict[str, Any]] = []
    governance: list[dict[str, Any]] = []
    auto_allowed = set(str(x) for x in (action_policy.get("auto_allowed_actions") or []))
    human_required = set(str(x) for x in (action_policy.get("human_approval_actions") or []))
    blocked = set(str(x) for x in (action_policy.get("blocked_actions") or []))

    for raw in actions:
        if not isinstance(raw, dict):
            continue
        action_type = str(raw.get("type") or "unknown").strip().lower()
        canonical = _canonical_action_name(action_type)
        decision = "allowed"
        reason = "permitted_by_action_policy"
        if canonical in blocked:
            decision = "blocked"
            reason = "blocked_by_action_policy"
        elif canonical in human_required and canonical not in auto_allowed:
            decision = "human_approval_required"
            reason = "requires_human_gate"
        elif canonical not in auto_allowed and canonical not in human_required:
            decision = "human_approval_required"
            reason = "not_in_auto_allowlist"
        governance.append(
            {
                "action_type": action_type,
                "canonical_action": canonical,
                "decision": decision,
                "reason": reason,
            }
        )
        if decision == "allowed":
            filtered.append(raw)
    return filtered, governance
