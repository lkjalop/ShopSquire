"""Fail-closed buyer and trace projections for unresolved workload turns.

The recommendation core owns sequencing; this module owns the repeated typed
control-envelope projection.  Keeping that boundary explicit prevents the core
orchestrator from growing every time a new fault receipt is added.
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping, Sequence

from src.app.services.research_control_loop import (
    ControlReceipt,
    ExecutionStateEnvelope,
    localize_control_faults,
    propose_sanitized_failure_lesson,
)


def _buyer_text(envelope: Any) -> str:
    return str(envelope.buyer_query or envelope.query or "")


def _attach_control_projection(resp: Any, control: ExecutionStateEnvelope) -> None:
    faults = localize_control_faults(control)
    resp.extras["execution_state_envelope"] = control.model_dump(mode="json")
    resp.extras["control_faults"] = [item.model_dump(mode="json") for item in faults]
    if faults:
        resp.extras["experiential_failure_lesson"] = propose_sanitized_failure_lesson(
            control, faults,
        ).model_dump(mode="json")


def project_named_workload_hold(
    *,
    resp: Any,
    envelope: Any,
    unresolved_workloads: Sequence[Mapping[str, Any]],
    question_text: str,
    model_identity: str,
) -> None:
    """Project one identity/research card and its component-level control receipts."""
    identities: list[dict[str, Any]] = []
    for item in unresolved_workloads:
        identity = item.get("identity_resolution")
        identity = identity if isinstance(identity, dict) else {}
        resolved_name = str(
            item.get("resolved_name") or identity.get("resolved_name") or ""
        ).strip()
        if resolved_name:
            identities.append({
                "requested_name": str(item.get("requested_name") or "").strip(),
                "resolved_name": resolved_name,
                "source": str(identity.get("source") or "").strip(),
                "source_url": str(
                    identity.get("source_url") or item.get("source_url") or ""
                ).strip(),
                "confidence": identity.get("confidence"),
                "status": str(item.get("status") or "identity_resolved"),
                "requirements_status": "material_requirements_missing",
            })

    resp.extras["ambiguity_exploration"] = {
        "schema_version": "ambiguity-exploration-v1",
        "case_id": str(envelope.session.get("case_id") or envelope.trace_id),
        "trace_id": envelope.trace_id,
        "retained_purpose": _buyer_text(envelope),
        "status": "context_only" if identities else "unresolved",
        "interpretations": [{
            "hypothesis_id": f"named-workload-{index + 1}",
            "label": (
                f"Likely official identity: {candidate['resolved_name']}; "
                "material requirements are still unresolved."
            ),
            "confidence": candidate.get("confidence"),
        } for index, candidate in enumerate(identities)],
        "next_question": {"text": question_text},
        "execution": (
            "provider lookup completed"
            if envelope.external_research_consent else "not executed"
        ),
        "evidence": "identity only" if identities else "none",
        "decision": "clarification required",
        "cart_authority": "none",
        "provider_accounting": {
            "external_calls": sum(
                1 for item in unresolved_workloads
                for attempt in list(item.get("provider_attempts") or [])
                if isinstance(attempt, dict) and bool(attempt.get("allow_live"))
            ),
            "paid_calls": 0,
        },
        "identity_candidates": identities,
    }
    identity_resolved = any(
        str(item.get("status") or "").startswith("identity_resolved")
        for item in unresolved_workloads
    )
    provider_status = "not_attempted"
    if envelope.external_research_consent:
        provider_error = any(
            any(
                str(attempt.get("status") or "") == "provider_error"
                for attempt in list(item.get("provider_attempts") or [])
                if isinstance(attempt, dict)
            )
            for item in unresolved_workloads
        )
        provider_status = "completed" if identity_resolved else "failed" if provider_error else "disabled"
    control = ExecutionStateEnvelope(
        case_id=str(envelope.session.get("case_id") or envelope.trace_id),
        case_revision=max(1, int(envelope.session.get("case_revision") or 1)),
        buyer_text_hash=hashlib.sha256(_buyer_text(envelope).encode("utf-8")).hexdigest(),
        model_identity=str(model_identity or "unknown"),
        model_status="degraded" if bool(resp.degraded) else "completed",
        material_concept_status="resolved" if identity_resolved else "unresolved",
        research_authority="granted" if envelope.external_research_consent else "required",
        provider_status=provider_status,
        evidence_status="identity_only" if identity_resolved else "none",
        requirement_status="blocked",
        catalog_authority="blocked",
        presentation_status="clarification_only",
        commerce_authority="none",
        receipts=(
            ControlReceipt(sequence=1, component="model", status="completed", authority="proposes", reason="Named workload proposed from buyer-authored text."),
            ControlReceipt(sequence=2, component="working_state", status="unresolved", authority="records", reason="Material workload identity or requirements remain unresolved."),
            ControlReceipt(sequence=3, component="invocation", status=provider_status, authority="retrieves", reason="Enrolled provider readiness and authorization evaluated."),
            ControlReceipt(sequence=4, component="checker", status="blocked", authority="authorizes", reason="No accepted material requirements authorize catalog fit."),
            ControlReceipt(sequence=5, component="presentation", status="clarification_only", authority="presents", reason="Buyer receives one evidence-resolution action, not a fit claim."),
        ),
    )
    _attach_control_projection(resp, control)


def project_semantic_hold(
    *,
    resp: Any,
    envelope: Any,
    semantic_case_id: str | None,
    concept_status: str,
    research_should_execute: bool,
    normalized_evidence: Iterable[Any],
    model_identity: str,
) -> None:
    """Record which component blocked a model-only semantic proposal."""
    normalized = tuple(normalized_evidence)
    status = str(concept_status or "").lower()
    if not envelope.external_research_consent:
        provider_status = "not_attempted"
    elif not research_should_execute:
        provider_status = "disabled"
    elif "timeout" in status or "deadline" in status:
        provider_status = "timeout"
    else:
        provider_status = "completed" if normalized else "failed"
    evidence_status = (
        "contradicted" if "contradict" in status
        else "stale" if "stale" in status
        else "accepted" if normalized else "none"
    )
    control = ExecutionStateEnvelope(
        case_id=str(semantic_case_id or envelope.trace_id),
        case_revision=max(1, int(envelope.session.get("case_revision") or 1)),
        buyer_text_hash=hashlib.sha256(_buyer_text(envelope).encode("utf-8")).hexdigest(),
        model_identity=str(model_identity or "unknown"),
        model_status="degraded" if bool(resp.degraded) else "completed",
        material_concept_status="unresolved",
        research_authority="granted" if envelope.external_research_consent else "required",
        provider_status=provider_status,
        evidence_status=evidence_status,
        requirement_status="blocked",
        catalog_authority="blocked",
        presentation_status="clarification_only",
        commerce_authority="none",
        receipts=(
            ControlReceipt(sequence=1, component="model", status="completed", authority="proposes", reason="Model proposed a material semantic interpretation."),
            ControlReceipt(sequence=2, component="working_state", status="unresolved", authority="records", reason="Canonical case retains the unresolved material concept."),
            ControlReceipt(sequence=3, component="invocation", status=provider_status, authority="retrieves", reason="Research authorization and provider outcome were recorded."),
            ControlReceipt(sequence=4, component="checker", status="blocked", authority="authorizes", reason="No accepted requirement set authorizes product fit."),
            ControlReceipt(sequence=5, component="presentation", status="clarification_only", authority="presents", reason="Budget conclusions and product shelves are suppressed."),
        ),
    )
    _attach_control_projection(resp, control)
