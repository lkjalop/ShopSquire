"""Pre-action deterministic challenge for commercial promise proposals."""

from __future__ import annotations

from typing import Any


def critique_promise(
    *,
    proposal: dict[str, Any],
    feasibility: dict[str, Any],
    calendar_expectation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    action = str(proposal.get("action") or "review")
    state = str(feasibility.get("feasibility") or "unknown")
    unknown_quantity = max(0, int(feasibility.get("unknown_quantity") or 0))
    calendar = calendar_expectation or {}
    calendar_state = str(calendar.get("calendar_state") or "unknown")
    freshness = str(calendar.get("freshness") or "unknown")
    if action in {"promise_full", "commit_full"} and state != "met":
        reasons.append("full_promise_not_supported")
    if action in {"promise_full", "commit_full"} and not feasibility.get("dependency_versions"):
        reasons.append("promise_dependencies_unversioned")
    if calendar_state == "unknown" or freshness in {"unknown", "missing", "stale"}:
        reasons.append("calendar_authority_unavailable")
    if str(proposal.get("payment_action") or "") == "capture_full" and unknown_quantity > 0:
        reasons.append("full_capture_against_unconfirmed_supply")
    substitution_without_consent = bool(proposal.get("substitute_selected")) and not bool(
        proposal.get("buyer_substitute_consent")
    )
    if substitution_without_consent:
        reasons.append("substitution_requires_buyer_consent")
    hard_block = {
        "full_promise_not_supported",
        "full_capture_against_unconfirmed_supply",
        "substitution_requires_buyer_consent",
    }.intersection(reasons)
    if hard_block:
        decision = "block"
    elif reasons:
        decision = "revise" if state != "unknown" else "unknown"
    else:
        decision = "uphold"
    return {
        "decision": decision,
        "reason_codes": reasons,
        "state_prevented": (
            "unconsented_substitution"
            if substitution_without_consent
            else "unsupported_commercial_promise"
            if hard_block
            else None
        ),
        "next_permitted_action": (
            "present_grounded_options"
            if hard_block
            else "request_missing_evidence"
            if reasons
            else action
        ),
        "external_action": "none",
        "authority": "deterministic_pre_action_critic",
    }
