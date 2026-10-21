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
import json

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
    compilation_scopes: list[dict[str, Any]] = Field(default_factory=list)
    missing_requirement_attributes: list[str] = Field(default_factory=list)
    literal_requirement_observations: list[dict[str, Any]] = Field(default_factory=list)
    requirement_completeness: Literal[
        "unknown", "none", "identity_only", "partial", "complete",
    ] = "unknown"
    catalog_authority: Literal["permitted", "provisional", "blocked", "unknown"]
    commerce_authority: Literal["none", "proposal_only", "approved"] = "none"
    next_action: str | None = Field(default=None, max_length=240)
    failure_code: str | None = Field(default=None, max_length=160)
    simulation_only: bool = False


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


def _unique_claims(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Deduplicate transported receipts; a repeated projection is not a claim."""
    return list({str(row.get("claim_id") or json.dumps(dict(row), sort_keys=True, default=str)): row
                 for row in rows if isinstance(row, Mapping)}.values())


def _identity(rows: list[Mapping[str, Any]]) -> ResearchIdentity | None:
    # Prefer an explicitly resolved, cited identity over a ranked discovery
    # page title. Candidate rows remain untrusted source metadata and grant no
    # fetch authority merely by appearing earlier in a mapping.
    # A structured provider row is the richest cited form: unlike the model's
    # earlier snippet-clamped proposal it carries stable publisher/app/release
    # identifiers. Reduce that row first so the terminal outcome cannot lose
    # fields merely because identity resolution happened before provider lookup.
    for row in rows:
        if str(row.get("status") or "").lower() != "resolved":
            continue
        title = row.get("canonical_title") or row.get("resolved_name")
        structured = bool(
            row.get("app_id") or row.get("provider_id") or row.get("source_url")
        )
        if title and structured:
            return ResearchIdentity(
                title=str(title)[:300],
                publisher=str(row.get("publisher") or "")[:300] or None,
                app_id=str(row.get("app_id") or "")[:100] or None,
                release_state=str(row.get("release_state") or "")[:100] or None,
                release_date=str(row.get("release_date") or "")[:100] or None,
            )
    for row in rows:
        if str(row.get("status") or "").lower() != "resolved":
            continue
        proposed = row.get("identity")
        if not isinstance(proposed, Mapping):
            continue
        title = proposed.get("canonical_title") or proposed.get("title")
        if title:
            return ResearchIdentity(
                title=str(title)[:300],
                publisher=str(proposed.get("publisher") or "")[:300] or None,
                app_id=str(proposed.get("app_id") or "")[:100] or None,
                release_state=str(proposed.get("release_state") or "")[:100] or None,
                release_date=str(proposed.get("release_date") or "")[:100] or None,
            )
    identity_attempts = [
        row for row in rows
        if "model_calls" in row
        and "authority" in row
        and ("identity" in row or str(row.get("failure_code") or "").startswith("identity_"))
    ]
    if identity_attempts:
        # Once the governed resolver has attempted the task, its unresolved or
        # rejected verdict is authoritative for identity status. Falling back
        # to the first discovery-page title can mislabel an unrelated result as
        # the buyer's product even though no commerce authority is granted.
        # A later revision-bound workload projection may already contain the
        # successfully cited identity even when the raw resolver receipt is
        # not retained in the same subtree. Prefer that typed projection below
        # before deciding the outcome is unresolved.
        if not any(row.get("canonical_title") or row.get("resolved_name") for row in rows):
            return None
    for row in rows:
        title = row.get("canonical_title") or row.get("resolved_name")
        if not title:
            continue
        return ResearchIdentity(
            title=str(title)[:300],
            publisher=str(row.get("publisher") or "")[:300] or None,
            app_id=str(row.get("app_id") or "")[:100] or None,
            release_state=str(row.get("release_state") or "")[:100] or None,
            release_date=str(row.get("release_date") or "")[:100] or None,
        )
    for row in rows:
        title = (
            row.get("title") if row.get("candidate_id") else None
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
    dispatched = [row for row in rows if row.get("provider_capability") == "WEB_DISCOVERY"
                  and row.get("external_call_dispatched") is True]
    for receipt in dispatched:
        if receipt.get("execution_status") == "failed" and receipt.get("error"):
            return str(receipt["error"])[:160]
    for row in rows:
        for key in ("failure_code", "error_code", "code", "rejection_reason"):
            value = str(row.get(key) or "").strip()
            if dispatched and value == "discovery_reachability_not_observed":
                continue  # pre-dispatch uncertainty cannot override an executed receipt
            if value and value not in {"none", "not_recorded"}:
                return value[:160]
    return None


def _manifest_coverage(rows, contract=None):
    # Scoped provider groups are assessed independently: attributes from two
    # different workloads cannot fill each other's missing obligations.
    from src.app.services.recommendation_core.requirement_scope import RequirementScope, scope_is_current
    scopes: dict[str, dict[str, Any]] = {}
    missing_attributes: set[str] = set()
    for row in rows:
        predicates = row.get("compiled_requirements")
        if not isinstance(predicates, list):
            continue
        groups: dict[tuple[str, ...], tuple[Any, set[str]]] = {}
        for predicate in predicates:
            if not isinstance(predicate, Mapping) or not predicate.get("compilation_scope"):
                continue
            try:
                scope = RequirementScope.model_validate(predicate["compilation_scope"])
            except ValueError:
                missing_attributes.add("valid_manifest_scope")
                continue
            scope_key = scope.model_dump_json()
            scopes[scope_key] = scope.model_dump(mode="json")
            # Container shape is not identity: one provider row can contain
            # obligations for several artifacts or versions.
            key = (scope_key, str(predicate.get("artefact_name") or "").casefold(),
                   str(predicate.get("artefact_version") or ""),
                   str(predicate.get("requirement_class") or "minimum"),
                   str(predicate.get("scope_caveat") or ""))
            if key not in groups:
                groups[key] = (scope, set())
            if predicate.get("verification_status") == "verified":
                groups[key][1].add(str(predicate.get("attribute_key") or ""))
        for key,(scope, present) in groups.items():
            if not scope_is_current(scope):
                missing_attributes.add("current_manifest_revision")
            if not scope.required_attributes:
                missing_attributes.add("manifest_obligations")
            required=set(scope.required_attributes)
            if (contract is not None and key[1]==contract.context.subject.casefold()
                    and key[2]==contract.context.version):
                required={o.attribute for o in contract.obligations if o.tier==key[3]}
            missing_attributes.update(required - present)

    return scopes, missing_attributes


def build_research_outcome(
    *,
    case_id: str,
    case_revision: int,
    operation_id: str | None,
    research: Mapping[str, Any] | None,
    requirements: Mapping[str, Any] | None,
    catalog_authority: str,
    commerce_authority: str,
    contract_receipt: Mapping[str, Any] | None = None,
) -> ResearchOutcome:
    """Reduce existing receipts without inventing execution or evidence."""

    research_data = dict(research or {})
    requirement_data = dict(requirements or {})
    rows = [*list(_dicts(research_data)), *list(_dicts(requirement_data))]
    identity = _identity(rows)
    # Observations are delivered independently of compiled/accepted predicates.
    # Repeated projections must not duplicate a cited publisher observation.
    literal_observations = {}
    for row in rows:
        for observation in row.get("literal_requirement_observations") or []:
            if not isinstance(observation, Mapping) or not observation.get("observation_id"):
                continue
            if observation.get("disposition") != "observed" or observation.get("fit_authority") != "none":
                continue
            if len(literal_observations) < 32:
                literal_observations[str(observation["observation_id"])] = dict(observation)

    certificate = next((
        row for row in rows
        if isinstance(row.get("claim_compilation"), Mapping)
        and isinstance(row.get("execution"), Mapping)
    ), None)
    compilation = dict(certificate.get("claim_compilation") or {}) if certificate else {}
    execution = dict(certificate.get("execution") or {}) if certificate else {}
    security = dict(certificate.get("security") or {}) if certificate else None

    from src.app.services.structured_requirement_claims import project_structured_requirement_claims
    structured_claims = project_structured_requirement_claims({"evidence": rows})
    accepted_rows = _unique_claims([
        *(requirement_data.get("accepted") or []),
        *(claim for claim in structured_claims if claim["authority_status"] == "verified_official"),
    ])
    rejected_rows = _unique_claims(requirement_data.get("rejected") or [])
    held_requirement_rows = _unique_claims([
        *(requirement_data.get("held") or []),
        *(claim for claim in structured_claims if claim["authority_status"] == "observed_held"),
    ])
    accepted = max(len(accepted_rows), int(compilation.get("accepted") or 0))
    provisional_rows = list(research_data.get("provisional_claims") or [])
    pending_review_rows = [
        row for row in rows
        if (
            str(row.get("acceptance_status") or "").lower()
            in {"pending", "pending_review", "pending_buyer_review"}
            or str(row.get("authority_status") or "").lower()
            in {"held", "observed_held", "pending_independent_policy_review"}
        )
    ]
    compilation_receipts = list(research_data.get("claim_compilation_receipts") or [])
    held = max(
        int(compilation.get("provisional") or 0),
        len(provisional_rows),
        len(held_requirement_rows),
        len(pending_review_rows),
        sum(int(row.get("provisional_claim_count") or 0) for row in compilation_receipts),
    )
    # The same compiler receipt can be carried by multiple projections. Count
    # its distinct rejected predicates, including connector-local rejections.
    compiler_rejections = {
        (
            str(item.get("claim_id") or ""),
            str(item.get("attribute_key") or ""),
            str(item.get("reason") or ""),
        )
        for row in rows
        for item in (row.get("claim_rejections") or [])
        if isinstance(item, Mapping)
    }
    rejected = max(
        len(rejected_rows), len(compiler_rejections), int(compilation.get("rejected") or 0),
    )
    # Compilation presence describes execution, not acceptance. Acceptance is
    # projected above from each predicate's explicit verification disposition.
    compiled = max((
        len(row.get("compiled_requirements") or [])
        for row in rows if isinstance(row.get("compiled_requirements"), list)
        and row.get("provider_id") and row.get("source_url")
        and row.get("status") == "resolved"
    ), default=0)
    # Held source claims may later be accepted or rejected for this case while
    # remaining held at publisher-policy level. Those are dispositions of the
    # same claims, not additional parsed claims.
    parsed = max(
        held,
        accepted + rejected,
        int(compilation.get("parsed") or 0),
    )

    selected_contract=None
    invalid_contract=False
    if contract_receipt and contract_receipt.get('state')!='unselected':
        from src.app.services.case_contract_binding import load_contract_by_id
        from src.app.services.structured_requirement_claims import project_structured_requirement_claims
        from src.app.services.requirement_contract import assess_contract_coverage
        try:
            candidate=load_contract_by_id(contract_receipt.get('contract_id'))
            claims=project_structured_requirement_claims({'evidence':rows})
            valid=(contract_receipt.get('state')=='current' and contract_receipt.get('case_id')==case_id
                and contract_receipt.get('case_revision')==case_revision
                and contract_receipt.get('contract_revision')==candidate.revision
                and contract_receipt.get('context')==candidate.context.model_dump()
                and assess_contract_coverage(candidate,context=candidate.context,claims=claims)['coverage_complete'])
            if valid:selected_contract=candidate
            else:invalid_contract=True
        except (ValueError,OSError):invalid_contract=True
    scopes, missing_attributes = _manifest_coverage(rows,selected_contract)
    if invalid_contract:missing_attributes.add('selected_contract_current_evidence')
    if accepted and not scopes and any(row.get("source_execution") for row in rows):
        # Enrolled-source acceptance proves provenance, not compiler coverage.
        # Make the actual blocker visible instead of returning partial + [] in
        # the shared API/UI/trace outcome.
        missing_attributes.add("manifest_scope_missing")
    completeness_value = str(_first(rows, "requirements_completeness") or "").lower()
    evidence_outcome = str(_first(rows, "evidence_outcome") or "").lower()
    if missing_attributes:
        completeness = "partial"
    elif scopes and not held:
        # Completeness belongs to the current manifest's obligations. An
        # unsupported extra predicate stays rejected, but cannot invalidate
        # independently verified predicates satisfying every obligation.
        completeness = "complete"
    elif any(row.get("claim_rejections") for row in rows):
        completeness = "partial"
    elif completeness_value in {"minimum_and_recommended", "complete", "accepted_complete"}:
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
    if identity and compiled:
        # A lower discovery tier may time out after an authoritative structured
        # provider has already resolved the canonical identity and material
        # requirements.  Preserve the diagnostic receipt, but do not downgrade
        # the buyer's canonical outcome.
        discovery_status = "completed"
    elif provider_statuses & {"running", "in_progress", "pending"}:
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
        # Structured evidence may be cached. Identity/compilation does not
        # attest that a fetch ran in this operation.
        fetch_status = "not_attempted"
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
    elif any(row.get("publisher_ownership_status") == "verified"
             and row.get("ownership_receipt_id") for row in rows):
        ownership = "verified"
    elif has_candidates:
        ownership = "discovered_candidate"
    elif resolution_status in {"not_enrolled", "unresolved", "ambiguous"}:
        ownership = "unresolved"
    else:
        ownership = "not_assessed"

    next_action = str(_first(rows, "next_action") or "").strip() or None
    failure = _failure_code(rows)
    identity_confirmation = next((
        row for row in rows
        if str(row.get("status") or "").lower() == "confirmation_required"
        and str(row.get("failure_code") or "").startswith("low_confidence_identity_")
    ), None)
    if identity_confirmation is not None:
        # A terminal identity decision is more actionable than diagnostic
        # rejections from earlier evidence-ladder rungs.
        failure = str(identity_confirmation["failure_code"])[:160]
        next_action = "confirm_canonical_identity"
    if held:
        next_action = next_action or "independent_policy_review"
        # A lower-tier cache miss may coexist with a successful canonical fetch.
        # The buyer's actionable blocker is the held-claim review, not that
        # diagnostic miss from an earlier evidence-ladder rung.
        failure = "independent_policy_human_signoff_pending"

    bounded_catalog = str(catalog_authority or "unknown").lower()
    if bounded_catalog not in {"permitted", "provisional", "blocked", "unknown"}:
        bounded_catalog = "unknown"
    if identity_confirmation is not None:
        bounded_catalog = "blocked"
    if bounded_catalog in {"permitted", "unknown"} and completeness == "partial":
        bounded_catalog = "blocked"
        failure = "requirements_incomplete"
        next_action = "complete_requirement_evidence"
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
        compilation_scopes=list(scopes.values()),
        missing_requirement_attributes=sorted(missing_attributes),
        literal_requirement_observations=list(literal_observations.values()),
        requirement_completeness=completeness,
        catalog_authority=bounded_catalog,
        commerce_authority=bounded_commerce,
        next_action=next_action,
        failure_code=failure,
        simulation_only=any(row.get('simulation_only') is True for row in rows),
    )


__all__ = ["ResearchIdentity", "ResearchOutcome", "build_research_outcome"]
