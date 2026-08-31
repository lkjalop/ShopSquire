"""One revision-bound buyer-visible outcome for every research path.

The platform has several evidence transports (enrolled origins, connector
providers, open-world discovery, and buyer URLs).  This projection deliberately
does not perform research or grant authority.  It reduces their already-recorded
receipts into one vocabulary consumed by chat, the buyer panel, and Decision
Trace.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResearchIdentity(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    title: str | None = None
    publisher: str | None = None
    app_id: str | None = None
    release_state: str | None = None
    release_date: str | None = None


class ResearchOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["research-outcome-v1"] = "research-outcome-v1"
    case_id: str = Field(min_length=1, max_length=200)
    case_revision: int = Field(ge=1)
    operation_id: str | None = Field(default=None, max_length=240)
    identity: ResearchIdentity | None = None
    discovery_status: Literal[
        "not_attempted", "running", "completed", "degraded", "failed",
    ] = "not_attempted"
    source_ownership_status: Literal[
        "not_assessed", "unresolved", "discovered_candidate", "observed_held",
        "accepted_case_only", "verified",
    ] = "not_assessed"
    url_security_receipt: dict[str, Any] | None = None
    fetch_status: Literal[
        "not_attempted", "running", "completed", "partial", "failed",
    ] = "not_attempted"
    parsed_claim_count: int = Field(default=0, ge=0)
    held_claim_count: int = Field(default=0, ge=0)
    accepted_claim_count: int = Field(default=0, ge=0)
    rejected_claim_count: int = Field(default=0, ge=0)
    requirement_completeness: Literal[
        "unknown", "none", "identity_only", "partial", "complete",
    ] = "unknown"
    catalog_authority: Literal["permitted", "provisional", "blocked", "unknown"]
    commerce_authority: Literal["none", "proposal_only", "approved"] = "none"
    next_action: str | None = Field(default=None, max_length=240)
    failure_code: str | None = Field(default=None, max_length=160)


def _dicts(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _dicts(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _dicts(item)


def _first(rows: Iterable[Mapping[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _identity(rows: list[Mapping[str, Any]]) -> ResearchIdentity | None:
    for row in rows:
        title = (
            row.get("canonical_title") or row.get("resolved_name")
            or (row.get("title") if row.get("candidate_id") else None)
        )
        if not title:
            continue
        return ResearchIdentity(
            title=str(title)[:300],
            publisher=str(row.get("publisher") or "")[:300] or None,
            app_id=str(row.get("app_id") or "")[:100] or None,
            release_state=str(row.get("release_state") or "")[:100] or None,
            release_date=str(row.get("release_date") or "")[:100] or None,
        )
    return None


def _failure_code(rows: list[Mapping[str, Any]]) -> str | None:
    for row in rows:
        for key in ("failure_code", "error_code", "code", "rejection_reason"):
            value = str(row.get(key) or "").strip()
            if value and value not in {"none", "not_recorded"}:
                return value[:160]
    return None


def build_research_outcome(
    *,
    case_id: str,
    case_revision: int,
    operation_id: str | None,
    research: Mapping[str, Any] | None,
    requirements: Mapping[str, Any] | None,
    catalog_authority: str,
    commerce_authority: str,
) -> ResearchOutcome:
    """Reduce existing receipts without inventing execution or evidence."""

    research_data = dict(research or {})
    requirement_data = dict(requirements or {})
    rows = [*list(_dicts(research_data)), *list(_dicts(requirement_data))]
    identity = _identity(rows)

    certificate = next((
        row for row in rows
        if isinstance(row.get("claim_compilation"), Mapping)
        and isinstance(row.get("execution"), Mapping)
    ), None)
    compilation = dict(certificate.get("claim_compilation") or {}) if certificate else {}
    execution = dict(certificate.get("execution") or {}) if certificate else {}
    security = dict(certificate.get("security") or {}) if certificate else None

    accepted_rows = list(requirement_data.get("accepted") or [])
    rejected_rows = list(requirement_data.get("rejected") or [])
    accepted = max(len(accepted_rows), int(compilation.get("accepted") or 0))
    provisional_rows = list(research_data.get("provisional_claims") or [])
    pending_review_rows = [
        row for row in rows
        if str(row.get("acceptance_status") or "").lower()
        in {"pending", "pending_review", "pending_buyer_review"}
    ]
    compilation_receipts = list(research_data.get("claim_compilation_receipts") or [])
    held = max(
        int(compilation.get("provisional") or 0),
        len(provisional_rows),
        len(pending_review_rows),
        sum(int(row.get("provisional_claim_count") or 0) for row in compilation_receipts),
    )
    rejected = max(len(rejected_rows), int(compilation.get("rejected") or 0))
    # Connector evidence may carry already-compiled accepted requirements.
    compiled = max((
        len(row.get("compiled_requirements") or [])
        for row in rows if isinstance(row.get("compiled_requirements"), list)
    ), default=0)
    if identity and compiled:
        accepted = max(accepted, compiled)
    # Held source claims may later be accepted or rejected for this case while
    # remaining held at publisher-policy level. Those are dispositions of the
    # same claims, not additional parsed claims.
    parsed = max(
        held,
        accepted + rejected,
        int(compilation.get("parsed") or 0),
    )

    completeness_value = str(_first(rows, "requirements_completeness") or "").lower()
    evidence_outcome = str(_first(rows, "evidence_outcome") or "").lower()
    if completeness_value in {"minimum_and_recommended", "complete", "accepted_complete"}:
        completeness = "complete"
    elif held or accepted or compiled or "partial" in completeness_value:
        completeness = "partial"
    elif identity:
        completeness = "identity_only"
    elif parsed == 0:
        completeness = "none" if rows else "unknown"
    else:
        completeness = "unknown"

    resolution_status = str(_first(rows, "status") or "").lower()
    has_candidates = any(isinstance(row.get("candidates"), list) and row.get("candidates") for row in rows)
    provider_statuses = {
        str(row.get("provider_status") or row.get("execution_status") or "").lower()
        for row in rows
    }
    if provider_statuses & {"running", "in_progress", "pending"}:
        discovery_status = "running"
    elif provider_statuses & {"failed", "timeout", "disabled", "degraded"}:
        discovery_status = "degraded"
    elif identity or has_candidates or provider_statuses & {"completed", "resolved"}:
        discovery_status = "completed"
    else:
        discovery_status = "not_attempted"

    fetch_value = str(execution.get("origin_fetch_status") or "").lower()
    accounting = next((
        row for row in rows if "official_origin_fetches" in row or "external_calls" in row
    ), {})
    source_execution_statuses = {
        str(row.get("execution_status") or row.get("deadline_status") or "").lower()
        for row in rows if row.get("source_id")
    }
    if fetch_value == "completed" or bool(execution.get("network_execution")):
        fetch_status = "completed"
    elif int(accounting.get("official_origin_fetches") or 0) > 0:
        fetch_status = "completed"
    elif source_execution_statuses & {"completed", "within_deadline"}:
        fetch_status = "completed"
    elif fetch_value in {"failed", "blocked"}:
        fetch_status = "failed"
    elif fetch_value in {"running", "in_progress"}:
        fetch_status = "running"
    elif "fetch" in evidence_outcome and parsed:
        fetch_status = "partial"
    elif identity and compiled:
        fetch_status = "completed"
    else:
        fetch_status = "not_attempted"

    authority_values = {
        str(row.get("authority_status") or row.get("authority") or "").lower()
        for row in rows
    }
    accepted_authority_values = {
        str(row.get("authority_status") or "").lower() for row in accepted_rows
    }
    if accepted_authority_values & {
        "case_origin_critic_accepted", "accepted_case_only",
    }:
        ownership = "accepted_case_only"
    elif held or "pending_review" in evidence_outcome or "claims_pending" in evidence_outcome:
        ownership = "observed_held"
    elif (authority_values | accepted_authority_values) & {
        "verified", "verified_official", "publisher_verified",
    } or (identity and compiled):
        ownership = "verified"
    elif has_candidates:
        ownership = "discovered_candidate"
    elif resolution_status in {"not_enrolled", "unresolved", "ambiguous"}:
        ownership = "unresolved"
    else:
        ownership = "not_assessed"

    next_action = str(_first(rows, "next_action") or "").strip() or None
    failure = _failure_code(rows)
    if held:
        next_action = next_action or "independent_policy_review"
        # A lower-tier cache miss may coexist with a successful canonical fetch.
        # The buyer's actionable blocker is the held-claim review, not that
        # diagnostic miss from an earlier evidence-ladder rung.
        failure = "independent_policy_human_signoff_pending"

    bounded_catalog = str(catalog_authority or "unknown").lower()
    if bounded_catalog not in {"permitted", "provisional", "blocked", "unknown"}:
        bounded_catalog = "unknown"
    bounded_commerce = str(commerce_authority or "none").lower()
    if bounded_commerce not in {"none", "proposal_only", "approved"}:
        bounded_commerce = "none"

    return ResearchOutcome(
        case_id=case_id,
        case_revision=case_revision,
        operation_id=operation_id,
        identity=identity,
        discovery_status=discovery_status,
        source_ownership_status=ownership,
        url_security_receipt=security,
        fetch_status=fetch_status,
        parsed_claim_count=parsed,
        held_claim_count=held,
        accepted_claim_count=accepted,
        rejected_claim_count=rejected,
        requirement_completeness=completeness,
        catalog_authority=bounded_catalog,
        commerce_authority=bounded_commerce,
        next_action=next_action,
        failure_code=failure,
    )


__all__ = ["ResearchIdentity", "ResearchOutcome", "build_research_outcome"]
