"""Canonical buyer-visible truth over research, evidence, and commerce state."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ResearchExecution = Literal[
    "NOT_ATTEMPTED", "DISCOVERY_ONLY", "OFFICIAL_FETCH_PARTIAL", "COMPLETE",
]
EvidenceStatus = Literal[
    "NONE", "CANDIDATE_ONLY", "ACCEPTED_PARTIAL", "ACCEPTED_COMPLETE",
]
FreshnessStatus = Literal["CURRENT", "STALE", "UNKNOWN"]
DecisionStatus = Literal["PROVISIONAL", "CONDITIONAL", "QUALIFIED", "FAILED"]
CommerceAuthority = Literal["NONE", "CONFIRMATION_PENDING", "ACTION_ALLOWED"]


class CanonicalProcurementTruth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["canonical-procurement-truth-v1"] = (
        "canonical-procurement-truth-v1"
    )
    case_id: str
    case_revision: int = Field(ge=1)
    evaluated_at: str
    research_execution: ResearchExecution
    evidence_status: EvidenceStatus
    freshness: FreshnessStatus
    decision_status: DecisionStatus
    commerce_authority: CommerceAuthority
    external_calls: int = Field(ge=0)
    paid_calls: int = Field(ge=0)
    cart_mutations: int = Field(ge=0)
    supplier_sends: int = Field(ge=0)
    reasons: tuple[str, ...]
    authority_source: Literal["deterministic_adjudicator"] = "deterministic_adjudicator"


def _utc_iso(value: datetime | str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise ValueError("truth_evaluation_time_requires_timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _freshness(watermarks: list[dict[str, Any]]) -> FreshnessStatus:
    states = {str(row.get("state") or "unknown").strip().lower() for row in watermarks}
    if not states or states <= {"unknown", "missing", "not_observed"}:
        return "UNKNOWN"
    if states & {"stale", "expired", "invalid"}:
        return "STALE"
    return "CURRENT" if states <= {"current", "fresh"} else "UNKNOWN"


def _research_and_evidence(
    research: dict[str, Any],
) -> tuple[ResearchExecution, EvidenceStatus]:
    execution = str(research.get("execution") or research.get("execution_mode") or "").lower()
    claims = [row for row in research.get("claims") or [] if isinstance(row, dict)]
    accepted = [
        row for row in claims
        if str(row.get("status") or row.get("verdict") or "").lower()
        in {"accepted", "verified", "supported"}
    ]
    candidates = research.get("publisher_candidates") or research.get("candidates") or []
    complete = bool(research.get("complete") or research.get("accepted_complete"))
    if complete or (accepted and len(accepted) == len(claims)):
        return "COMPLETE", "ACCEPTED_COMPLETE"
    if accepted:
        return "OFFICIAL_FETCH_PARTIAL", "ACCEPTED_PARTIAL"
    if candidates or "discovery" in execution:
        return "DISCOVERY_ONLY", "CANDIDATE_ONLY"
    if "live" in execution or "official" in execution or "fetch" in execution:
        return "OFFICIAL_FETCH_PARTIAL", "NONE"
    return "NOT_ATTEMPTED", "NONE"


def adjudicate_procurement_truth(
    *,
    state_data: dict[str, Any],
    evidence_watermarks: list[dict[str, Any]] | None = None,
    provider_accounting: dict[str, Any] | None = None,
    evaluated_at: datetime | str | None = None,
    cart_mutations: int = 0,
    supplier_sends: int = 0,
) -> CanonicalProcurementTruth:
    research = dict(state_data.get("research") or {})
    fulfilment = dict(state_data.get("fulfilment") or {})
    authority = dict(state_data.get("authority") or {})
    accounting = dict(provider_accounting or research.get("provider_accounting") or {})
    watermarks = list(evidence_watermarks or [])
    research_execution, evidence_status = _research_and_evidence(research)
    freshness = _freshness(watermarks)
    commercial = dict(fulfilment.get("commercial_decision") or {})
    commercial_status = str(commercial.get("status") or "not_evaluated").upper()
    if commercial_status.startswith("QUALIFIED"):
        decision_status: DecisionStatus = "QUALIFIED"
    elif commercial_status in {"FAILED_REQUIREMENT", "OVER_BUDGET"}:
        decision_status = "FAILED"
    elif commercial_status.startswith("CONDITIONAL") or commercial_status == "UNVERIFIED":
        decision_status = "CONDITIONAL"
    else:
        decision_status = "PROVISIONAL"

    action_requested = bool(authority.get("action_allowed") is True)
    confirmation_pending = bool(
        authority.get("confirmation_pending") is True
        or fulfilment.get("pending_cart_change")
        or fulfilment.get("choice")
    )
    if action_requested and decision_status == "QUALIFIED" and freshness == "CURRENT":
        commerce_authority: CommerceAuthority = "ACTION_ALLOWED"
    elif confirmation_pending:
        commerce_authority = "CONFIRMATION_PENDING"
    else:
        commerce_authority = "NONE"

    reasons: list[str] = []
    if research_execution == "NOT_ATTEMPTED":
        reasons.append("External research was not attempted.")
    if evidence_status in {"NONE", "CANDIDATE_ONLY"}:
        reasons.append("Accepted requirement evidence is incomplete.")
    if freshness != "CURRENT":
        reasons.append("Current operational freshness is not established.")
    if commerce_authority == "NONE":
        reasons.append("No cart, supplier, payment, or shipment authority is granted.")
    elif commerce_authority == "CONFIRMATION_PENDING":
        reasons.append("A commercial change requires revision-bound buyer confirmation.")
    if cart_mutations and commerce_authority != "ACTION_ALLOWED":
        reasons.append("Invariant violation: cart mutation occurred without action authority.")
        decision_status = "FAILED"
    if supplier_sends and commerce_authority != "ACTION_ALLOWED":
        reasons.append("Invariant violation: supplier send occurred without action authority.")
        decision_status = "FAILED"

    return CanonicalProcurementTruth(
        case_id=str(state_data.get("case_id") or "unbound"),
        case_revision=int(state_data.get("revision") or 1),
        evaluated_at=_utc_iso(evaluated_at),
        research_execution=research_execution,
        evidence_status=evidence_status,
        freshness=freshness,
        decision_status=decision_status,
        commerce_authority=commerce_authority,
        external_calls=int(accounting.get("external_calls") or 0),
        paid_calls=int(accounting.get("paid_calls") or 0),
        cart_mutations=cart_mutations,
        supplier_sends=supplier_sends,
        reasons=tuple(reasons),
    )


def adjudicate_exploration_truth(payload: dict[str, Any]) -> CanonicalProcurementTruth:
    """Map the ambiguity/research projection onto the same canonical vocabulary."""
    execution = str(payload.get("execution") or "").lower()
    evidence = str(payload.get("evidence") or "").lower()
    decision = str(payload.get("decision") or "").lower()
    research: dict[str, Any] = {
        "execution": execution,
        "provider_accounting": payload.get("provider_accounting") or {},
    }
    if "candidate" in evidence:
        research["candidates"] = [{}]
    elif "compiled" in evidence:
        research["claims"] = [{"status": "accepted"}]
        research["complete"] = True
    state = {
        "case_id": payload.get("case_id") or "unbound",
        "revision": int(payload.get("case_revision") or 1),
        "research": research,
        "fulfilment": {
            "commercial_decision": {
                "status": (
                    "CONDITIONAL_NOW" if "conditional" in decision
                    else "not_evaluated"
                ),
            },
        },
        "authority": {},
    }
    return adjudicate_procurement_truth(
        state_data=state,
        provider_accounting=payload.get("provider_accounting") or {},
        evaluated_at=payload.get("evaluated_at"),
    )


__all__ = [
    "CanonicalProcurementTruth", "adjudicate_exploration_truth",
    "adjudicate_procurement_truth",
]
