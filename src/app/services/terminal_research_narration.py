"""Deterministic buyer narration derived from the canonical terminal outcome.

This module does not infer research truth.  It only prevents an earlier model
or catalog sentence from contradicting the revision-bound evidence outcome.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_MODEL_FAILURE_MESSAGES = {
    "router_output_invalid": (
        "The workload interpreter returned output that could not be validated. "
        "Product fit was not established; no cart or supplier action was authorized."
    ),
    "router_output_truncated": (
        "I could not complete the workload interpretation because the model response was "
        "truncated. Research and product fit were not concluded; no product or commerce "
        "action was authorized."
    ),
    "model_execution_timeout": (
        "I could not complete the workload interpretation before its deadline. Research "
        "and product fit were not concluded; no product or commerce action was authorized."
    ),
    "model_execution_unavailable": (
        "The workload interpreter was unavailable. Research and product fit were not "
        "concluded; no product or commerce action was authorized."
    ),
}


def terminal_research_narration(
    *,
    research_outcome: Mapping[str, Any] | None,
    execution_evidence: Mapping[str, Any] | None,
    existing_message: str,
    subject_role: str | None = None,
) -> str:
    """Return canonical failure/held narration, otherwise preserve the answer."""

    # Host-workload evidence cannot answer a different purchased object. The
    # caller supplies the validated role; no title/keyword matching occurs here.
    if subject_role in {"PROCURE_SUBJECT", "ADJACENT_PRODUCT"}:
        return str(existing_message or "")
    outcome = dict(research_outcome or {})
    if outcome.get("failure_code") == "requirements_incomplete":
        identity = outcome.get("identity")
        title = str(identity.get("title") or "").strip() if isinstance(identity, Mapping) else ""
        subject = f"For {title}, research" if title else "Research"
        return (
            f"{subject} accepted {int(outcome.get('accepted_claim_count') or 0)} requirement claims, "
            "but requirements coverage remains partial. I cannot confirm full compatibility "
            "or qualify a product until the missing requirements are established. "
            "No cart or supplier action was authorized."
        )
    evidence = dict(execution_evidence or {})
    failure_code = str(evidence.get("failure_code") or "").strip()
    research_concluded = bool(
        str(outcome.get("discovery_status") or "").lower() == "completed"
        and (
            int(outcome.get("accepted_claim_count") or 0) > 0
            or int(outcome.get("held_claim_count") or 0) > 0
            or str(outcome.get("requirement_completeness") or "").lower()
            in {"complete", "partial"}
        )
    )
    if failure_code in _MODEL_FAILURE_MESSAGES and not research_concluded:
        return _MODEL_FAILURE_MESSAGES[failure_code]
    if failure_code in _MODEL_FAILURE_MESSAGES and research_concluded:
        return (
            "Initial workload interpretation was degraded, but the later governed "
            f"research outcome completed. {str(existing_message or '').strip()}"
        ).strip()

    held = int(outcome.get("held_claim_count") or 0)
    research_failure = str(outcome.get("failure_code") or "")
    if (outcome.get("catalog_authority") == "blocked" and research_failure
            and not research_failure.startswith("low_confidence_identity_")
            and not held and not int(outcome.get("accepted_claim_count") or 0)):
        return (
            "I could not complete the required research. I cannot establish product "
            "compatibility or budget fit yet. No cart or supplier action was authorized."
        )
    if held <= 0:
        return str(existing_message or "")

    parsed = max(held, int(outcome.get("parsed_claim_count") or 0))
    accepted = int(outcome.get("accepted_claim_count") or 0)
    identity = outcome.get("identity") if isinstance(outcome.get("identity"), Mapping) else {}
    title = str((identity or {}).get("title") or "the named workload").strip()
    if accepted > 0:
        held_boundary = (
            f"{held} additional claim{'s remain' if held != 1 else ' remains'} held pending "
            "independent human source-policy review. Those held claims do not verify products "
            "or authorize commerce; the accepted claims are not downgraded."
        )
        existing = str(existing_message or "").strip()
        return f"{existing} {held_boundary}".strip()
    return (
        f"I found the official source for {title} and parsed {parsed} cited "
        f"requirement claim{'s' if parsed != 1 else ''}. {held} "
        f"claim{'s remain' if held != 1 else ' remains'} held pending independent human "
        "source-policy review. Recommendations may be explored only as provisional; no "
        "product is verified and no cart or supplier action was authorized."
    )


__all__ = ["terminal_research_narration"]
