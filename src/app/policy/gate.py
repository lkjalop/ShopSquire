from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal

import os

from src.app.config import load_feature_flags, get_settings
from src.app.security.refund_window_guard import evaluate_refund_aggregate_window


Decision = Literal["allow", "review", "deny"]


@dataclass
class PolicyGateResult:
    decision: Decision
    reasons: List[str]
    rule_hits: Dict[str, float]
    policy_version: str
    compliance_tags: List[str]
    action: str | None = None
    approval_required: bool = False


def _contains_sensitive_fields(payload: Dict[str, Any]) -> bool:
    keywords = ("card", "cvv", "pan", "ssn", "passport", "password", "api_key", "secret")
    for k, v in payload.items():
        key = str(k).lower()
        if any(tok in key for tok in keywords):
            return True
        if isinstance(v, str) and any(tok in v.lower() for tok in keywords):
            return True
    return False


def evaluate_policy_gate(context: Dict[str, Any]) -> PolicyGateResult:
    """Deterministic policy gate for tool calls and request decisions."""
    tool = str(context.get("tool") or "")
    params = context.get("params") or {}
    risk = float(context.get("risk_score") or 0.0)
    policy_version = str(context.get("policy_version") or "2026-01-27")
    request_type = str(context.get("request_type") or "")
    signals = context.get("signals") or {}
    severity = str(context.get("severity") or "info")
    pii_warn_count = int(context.get("pii_warn_count") or 0)
    ai_assisted = bool(context.get("ai_assisted", False))
    buyer_type = str(context.get("buyer_type") or context.get("tenant_profile") or "").lower()
    compliance_provided = bool(context.get("compliance_provided"))

    thresholds = {}
    try:
        flags = load_feature_flags(get_settings().feature_flags_path) or {}
        thresholds = flags.get("POLICY_THRESHOLDS", {}) if isinstance(flags.get("POLICY_THRESHOLDS"), dict) else {}
    except Exception:
        thresholds = {}

    def _thr_float(key: str, default: float) -> float:
        try:
            v = thresholds.get(key, default)
            return float(v)
        except Exception:
            return default

    def _thr_bool(key: str, default: bool) -> bool:
        try:
            v = thresholds.get(key, default)
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in ("1", "true", "yes", "on")
        except Exception:
            return default

    auto_refund_max = _thr_float("auto_refund_max_usd", 150.0)
    auto_discount_max = _thr_float("auto_discount_max", 0.15)
    require_approval_for_pci = _thr_bool("require_approval_for_pci", True)
    require_approval_for_review = _thr_bool("require_approval_for_policy_review", False)
    risk_medium_min = _thr_float("risk_score_medium_min", 0.6)
    risk_high_min = _thr_float("risk_score_high_min", 0.8)

    # Dynamic threshold adjustment from persistent risk register snapshots.
    # When any domain is "high" risk, tighten auto-approve thresholds.
    try:
        from src.app.routers.admin_grc import get_latest_risk_bands
        rr_bands = get_latest_risk_bands()
        high_domains = [d for d, b in rr_bands.items() if b == "high"]
        if high_domains:
            # Tighten thresholds proportionally: each high domain reduces them
            factor = max(0.3, 1.0 - 0.15 * len(high_domains))
            risk_high_min = max(0.3, risk_high_min * factor)
            risk_medium_min = max(0.2, risk_medium_min * factor)
            auto_refund_max = max(25.0, auto_refund_max * factor)
    except Exception:
        pass
    high_risk_tools = thresholds.get("high_risk_tools") or ["refund.issue", "payout.send", "chargeback.override", "price.override"]
    cancel_after_ship_statuses = thresholds.get("cancel_after_ship_statuses") or ["shipped", "delivered", "out_for_delivery"]
    repeat_refund_24h_min = int(thresholds.get("repeat_refund_24h_min", 2) or 2)

    rule_hits: Dict[str, float] = {}
    reasons: List[str] = []
    compliance_tags: List[str] = []
    action: str | None = None
    approval_required = False

    if signals.get("pci"):
        compliance_tags.append("PCI-DSS")
    if signals.get("pii") or signals.get("gdpr"):
        compliance_tags.append("GDPR")
    if ai_assisted:
        compliance_tags.extend(["ISO42001", "EU-AI-Act"])
    if buyer_type in ("government", "enterprise"):
        compliance_tags.append("SOC2")

    if _contains_sensitive_fields(params):
        rule_hits["pci_sensitive_fields"] = 0.9
        reasons.append("Sensitive payment data detected in tool params.")

    try:
        high_risk_set = set(map(str, high_risk_tools))
    except Exception:
        high_risk_set = {"refund.issue", "payout.send", "chargeback.override", "price.override"}
    if tool in high_risk_set:
        rule_hits["high_risk_tool"] = 0.7
        reasons.append("High-risk tool call requires policy review.")
        approval_required = True

    if tool == "order.cancel":
        status = str(params.get("shipment_status") or params.get("order_status") or params.get("status") or "").lower()
        try:
            shipped_set = set(map(lambda s: str(s).lower(), cancel_after_ship_statuses))
        except Exception:
            shipped_set = {"shipped", "delivered", "out_for_delivery"}
        if status in shipped_set:
            rule_hits["cancel_after_ship"] = 0.7
            reasons.append("Order already shipped; cancellation requires review.")
            approval_required = True

    refund_amount = params.get("amount") or params.get("amount_cents") or params.get("refund_amount")
    try:
        refund_value = float(refund_amount) / 100.0 if "cents" in str(refund_amount) else float(refund_amount)
    except Exception:
        refund_value = None
    if refund_value is not None and refund_value > auto_refund_max:
        rule_hits["refund_above_threshold"] = 0.7
        reasons.append("Refund exceeds auto-approval threshold.")
        approval_required = True

    # §3.8 — aggregate refund action window guard (cumulative USD/hour per actor)
    try:
        is_refund_action = bool(
            tool in ("refund.issue", "refund.create", "return.refund")
            or request_type in ("refund", "refund_request", "return_request")
            or refund_value is not None
        )
        if is_refund_action:
            actor = str(
                context.get("actor_id")
                or context.get("uid")
                or context.get("source_ip")
                or context.get("ip")
                or "anon"
            )
            triggered, agg = evaluate_refund_aggregate_window(actor=actor, params=params)
            if triggered:
                rule_hits["refund_aggregate_hourly_limit"] = 0.8
                reasons.append("Cumulative refund amount in 1h exceeds threshold; human review required.")
                approval_required = True
    except Exception:
        pass

    discount_pct = params.get("discount_pct") or params.get("discount_percent") or params.get("override_percent")
    try:
        discount_value = float(discount_pct)
        if discount_value > 1.0:
            discount_value = discount_value / 100.0
    except Exception:
        discount_value = None
    if discount_value is not None and discount_value > auto_discount_max:
        rule_hits["discount_above_threshold"] = 0.7
        reasons.append("Discount exceeds auto-approval threshold.")
        approval_required = True

    if params.get("return_window_days") and params.get("days_since_delivery"):
        try:
            if int(params["days_since_delivery"]) > int(params["return_window_days"]):
                rule_hits["return_outside_window"] = 0.8
                reasons.append("Return request outside policy window.")
        except Exception:
            pass

    if params.get("order_id") and params.get("reference_order_id"):
        if str(params.get("order_id")) != str(params.get("reference_order_id")):
            rule_hits["order_id_mismatch"] = 0.6
            reasons.append("Order ID mismatch on refund/return request.")

    if params.get("refunds_last_24h"):
        try:
            if int(params.get("refunds_last_24h") or 0) >= repeat_refund_24h_min:
                rule_hits["repeat_refund_24h"] = 0.6
                reasons.append("Multiple refund attempts in 24h.")
        except Exception:
            pass

    if params.get("delivery_address_changed"):
        rule_hits["address_changed_after_purchase"] = 0.6
        reasons.append("Delivery address changed after purchase.")

    if signals.get("pci") or (signals.get("pii") and context.get("pii_types") and "ssn" in (context.get("pii_types") or [])):
        rule_hits["pci_or_ssn"] = 0.7
        reasons.append("Sensitive identity or payment data detected.")
        approval_required = approval_required or require_approval_for_pci
        if pii_warn_count >= 1:
            rule_hits["repeat_sensitive_data"] = 0.95
            reasons.append("Repeated sensitive data after warning.")
    if severity in ("high", "critical"):
        rule_hits["security_high"] = 0.8
        reasons.append("Security severity requires review.")
        approval_required = True
    if risk >= risk_high_min:
        rule_hits["risk_score_high"] = 0.8
        reasons.append("Risk score exceeds threshold.")
        approval_required = True
    if risk_medium_min <= risk < risk_high_min:
        rule_hits["risk_score_medium"] = 0.6
        reasons.append("Risk score in medium band.")

    if buyer_type in ("government", "enterprise") and not compliance_provided:
        rule_hits["compliance_missing"] = 0.6
        reasons.append("Compliance requirements not supplied for enterprise/government.")

    if any(score >= 0.8 for score in rule_hits.values()):
        return PolicyGateResult("deny", reasons, rule_hits, policy_version, compliance_tags, action, approval_required)
    if rule_hits:
        # If sensitive data detected for the first time, allow a soft warning instead of immediate block.
        if "pci_or_ssn" in rule_hits and pii_warn_count == 0:
            action = "warn"
        if require_approval_for_review:
            approval_required = True
        return PolicyGateResult("review", reasons, rule_hits, policy_version, compliance_tags, action, approval_required)
    return PolicyGateResult("allow", reasons, rule_hits, policy_version, compliance_tags, action, approval_required)
