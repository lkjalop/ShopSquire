"""Persist ordinary shopping-case decisions as immutable, replayable runs.

This is the transaction-bound bridge between the shopping-case workflow and
the generic decision-run ledger.  It projects only artifacts that the route
actually produced; it does not rerun research, ranking, or commerce logic.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable

from src.app.services.procurement_case_state import ProcurementCaseState
from src.app.services.procurement_decision_run import (
    EvidenceWatermark,
    StageReceipt,
    create_decision_run,
    create_decision_snapshot,
    persist_decision_run,
)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _candidate_skus(shelves: dict[str, Any]) -> list[str]:
    found: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            sku = str(value.get("sku") or value.get("retailer_sku") or "").strip()
            if sku and sku not in found:
                found.append(sku)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(shelves)
    return found[:100]


def _watermark_state(claim: dict[str, Any]) -> str:
    freshness = str(claim.get("freshness_status") or "").casefold()
    if freshness in {"fresh", "current"}:
        return "current"
    if freshness == "stale":
        return "stale"
    if freshness in {"unavailable", "empty", "undisclosed"}:
        return freshness
    return "undisclosed"


def _evidence_watermarks(
    claims: Iterable[dict[str, Any]], *, fallback_observed_at: str,
) -> tuple[EvidenceWatermark, ...]:
    rows: list[EvidenceWatermark] = []
    seen: set[tuple[str, str]] = set()
    for claim in claims:
        source = str(
            claim.get("source_id")
            or claim.get("source_reference")
            or claim.get("evidence_class")
            or "buyer_supplied"
        ).strip()
        observed_at = str(claim.get("observed_at") or fallback_observed_at)
        key = (source, observed_at)
        if key in seen:
            continue
        seen.add(key)
        rows.append(EvidenceWatermark(
            source=source[:160],
            observed_at=observed_at,
            source_version=str(claim.get("claim_id") or "")[:160] or None,
            content_hash=_digest({
                "claim_id": claim.get("claim_id"),
                "statement": claim.get("statement") or claim.get("source_excerpt"),
                "citation_url": claim.get("citation_url"),
            }),
            state=_watermark_state(claim),
        ))
    return tuple(rows)


def _receipt(
    *, stage: str, index: int, now: str, snapshot_hash: str,
    output: Any | None, inputs: tuple[str, ...], outputs: tuple[str, ...],
    dependency_stage_id: str | None = None, reason_code: str | None = None,
) -> StageReceipt:
    completed = output is not None
    return StageReceipt(
        stage=stage,
        stage_id=f"shopping-case-{index:02d}-{stage.replace('_', '-')}",
        status="completed" if completed else "not_run",
        started_at=now,
        completed_at=now,
        input_hash=snapshot_hash,
        output_hash=_digest(output) if completed else None,
        reason_code=None if completed else (reason_code or f"{stage}_not_produced"),
        dependency_stages=(),
        input_artifact_refs=inputs,
        output_artifact_refs=outputs,
        dependency_stage_ids=(dependency_stage_id,) if dependency_stage_id else (),
    )


def persist_requirement_acceptance_decision(
    db: Any,
    *,
    tenant_id: str,
    case_id: str,
    case_revision: int,
    retained_purpose: str,
    proposal_id: str,
    proposal_version: int,
    accepted_claims: list[dict[str, Any]],
    product_shelves: dict[str, Any],
    corroboration: dict[str, Any] | None,
    qualification_authority: str,
    observed_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Persist the accepted-evidence product decision in the caller transaction."""

    known = (observed_at or _utc_now()).astimezone(timezone.utc)
    research = dict((corroboration or {}).get("research") or {})
    official_claims = [
        dict(row) for row in research.get("claims") or [] if isinstance(row, dict)
    ]
    all_claims = [*accepted_claims, *official_claims]
    plan = dict((corroboration or {}).get("research_plan") or {})
    hypotheses = [
        str(row.get("label") or row.get("hypothesis_id") or "").strip()
        for row in plan.get("hypotheses") or [] if isinstance(row, dict)
    ]
    hypotheses = [row for row in hypotheses if row]
    candidate_skus = _candidate_skus(product_shelves)
    state = ProcurementCaseState(
        case_id=case_id,
        revision=case_revision,
        objective=retained_purpose,
        workloads=hypotheses[:20],
        candidate_skus=candidate_skus,
        research={
            "status": (corroboration or {}).get("status") or "not_requested",
            "evidence_outcome": (corroboration or {}).get("evidence_outcome") or "buyer_accepted",
            "provider_accounting": research.get("provider_accounting") or {
                "external_calls": 0, "paid_calls": 0,
            },
        },
        requirements={"accepted": all_claims},
        authority={
            "qualification": qualification_authority,
            "commercial": "none",
            "cart": "none",
        },
    )
    watermarks = _evidence_watermarks(
        all_claims, fallback_observed_at=known.isoformat(),
    )
    snapshot = create_decision_snapshot(
        state,
        tenant_id=tenant_id,
        knowledge_cutoff=known,
        evaluation_time=known,
        evidence_watermarks=watermarks,
    )
    now = known.isoformat()
    stage_outputs: list[tuple[str, Any | None, tuple[str, ...], tuple[str, ...], str | None]] = [
        (
            "interpretation", plan or {"retained_purpose": retained_purpose},
            ("buyer:outcome",), ("interpretation:hypotheses",), None,
        ),
        (
            "evidence", all_claims or None,
            ("interpretation:hypotheses", "evidence:buyer-accepted"),
            ("requirements:accepted", "evidence:watermarks"),
            "no_accepted_evidence",
        ),
        (
            "catalog_retrieval", candidate_skus or None,
            ("interpretation:hypotheses", "catalog:exact-configurations"),
            ("catalog:candidate-skus",), "no_exact_catalog_candidates",
        ),
        (
            "fit", product_shelves or None,
            ("requirements:accepted", "catalog:candidate-skus"),
            ("fit:verdicts",), "fit_projection_not_produced",
        ),
        (
            "commercial", product_shelves or None,
            ("fit:verdicts", "price:current", "availability:current"),
            ("commercial:shelves",), "commercial_projection_not_produced",
        ),
        (
            "fulfilment", None,
            ("commercial:shelves", "supplier:offers"),
            ("fulfilment:options",), "supplier_decision_not_requested",
        ),
        (
            "response", {
                "qualification_authority": qualification_authority,
                "candidate_count": len(candidate_skus),
                "evidence_count": len(all_claims),
            },
            ("fit:verdicts", "commercial:shelves"),
            ("response:shopping-case",), None,
        ),
    ]
    receipts: list[StageReceipt] = []
    prior_stage_id: str | None = None
    for index, (stage, output, inputs, outputs, reason) in enumerate(stage_outputs):
        receipt = _receipt(
            stage=stage, index=index, now=now, snapshot_hash=snapshot.state_hash,
            output=output, inputs=inputs, outputs=outputs,
            dependency_stage_id=prior_stage_id, reason_code=reason,
        )
        receipts.append(receipt)
        prior_stage_id = receipt.stage_id
    run = create_decision_run(
        snapshot,
        idempotency_key=(
            idempotency_key or f"requirement:{proposal_id}:v{proposal_version}"
        ),
        status="completed" if all_claims and product_shelves else "degraded",
        stage_receipts=tuple(receipts),
        now=known,
    )
    persist_decision_run(db, run, commit=False)
    return {
        "run_id": run.run_id,
        "case_id": case_id,
        "case_revision": case_revision,
        "knowledge_cutoff": snapshot.knowledge_cutoff,
        "evaluation_time": snapshot.evaluation_time,
        "status": run.status,
        "stage_count": len(receipts),
        "evidence_watermarks": [row.model_dump(mode="json") for row in watermarks],
        "persistence_status": "persisted",
        "commercial_authority_granted": False,
    }


def persist_fulfilment_selection_decision(
    db: Any,
    *,
    tenant_id: str,
    case_id: str,
    case_revision: int,
    retained_purpose: str,
    selection: Any,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    """Append an ordinary supplier/availability decision without cart authority."""

    from src.app.services.procurement_decision_run import load_decision_runs

    known = (observed_at or _utc_now()).astimezone(timezone.utc)
    prior = load_decision_runs(db, tenant_id=tenant_id, case_id=case_id, limit=1)
    if prior:
        state_data = prior[-1].snapshot.case_state.model_dump(mode="python")
        prior_watermarks = prior[-1].snapshot.evidence_watermarks
    else:
        state_data = ProcurementCaseState(
            case_id=case_id, revision=case_revision, objective=retained_purpose,
        ).model_dump(mode="python")
        prior_watermarks = ()
    selected_sku = str(selection.preferred_sku)
    if selection.selected_offer_id:
        selected_offer = next(
            (row for row in selection.offers if row.offer_id == selection.selected_offer_id), None,
        )
        if selected_offer is not None:
            selected_sku = str(selected_offer.offered_sku)
    state_data.update({
        "revision": case_revision,
        "objective": retained_purpose,
        "selected_sku": selected_sku,
        "requested_quantity": int(selection.requested_quantity),
        "fulfilment": {
            "selection_id": selection.selection_id,
            "selection_revision": int(selection.revision),
            "choice": selection.choice,
            "available_now": int(selection.available_now),
            "offers": [row.model_dump(mode="json") for row in selection.offers],
            "status": selection.status,
        },
        "authority": {
            **dict(state_data.get("authority") or {}),
            "supplier_send": "none",
            "cart": "none",
            "resolution_owner": "buyer",
        },
    })
    state = ProcurementCaseState.model_validate(state_data)
    snapshot = create_decision_snapshot(
        state,
        tenant_id=tenant_id,
        knowledge_cutoff=known,
        evaluation_time=known,
        evidence_watermarks=prior_watermarks,
    )
    now = known.isoformat()
    selection_json = selection.model_dump(mode="json")
    commercial = _receipt(
        stage="commercial", index=0, now=now, snapshot_hash=snapshot.state_hash,
        output={
            "requested_quantity": selection.requested_quantity,
            "available_now": selection.available_now,
        },
        inputs=("fit:verdicts", "inventory:current", "price:current"),
        outputs=("commercial:quantity-gap",),
    )
    fulfilment = _receipt(
        stage="fulfilment", index=1, now=now, snapshot_hash=snapshot.state_hash,
        output=selection_json,
        inputs=("commercial:quantity-gap", "supplier:offers", "delivery:observations"),
        outputs=("fulfilment:buyer-selection",),
        dependency_stage_id=commercial.stage_id,
    )
    response = _receipt(
        stage="response", index=2, now=now, snapshot_hash=snapshot.state_hash,
        output={
            "status": selection.status,
            "choice": selection.choice,
            "cart_mutation": "not_authorized",
            "supplier_send": "not_performed",
        },
        inputs=("fulfilment:buyer-selection",),
        outputs=("response:supplier-continuation",),
        dependency_stage_id=fulfilment.stage_id,
    )
    run = create_decision_run(
        snapshot,
        idempotency_key=f"fulfilment:{selection.selection_id}:v{selection.revision}",
        status="completed",
        stage_receipts=(commercial, fulfilment, response),
        now=known,
    )
    persist_decision_run(db, run)
    return {
        "run_id": run.run_id,
        "case_id": case_id,
        "case_revision": case_revision,
        "knowledge_cutoff": snapshot.knowledge_cutoff,
        "evaluation_time": snapshot.evaluation_time,
        "status": run.status,
        "stage_count": len(run.stage_receipts),
        "evidence_watermarks": [
            row.model_dump(mode="json") for row in snapshot.evidence_watermarks
        ],
        "persistence_status": "persisted",
        "commercial_authority_granted": False,
    }


__all__ = [
    "persist_fulfilment_selection_decision",
    "persist_requirement_acceptance_decision",
]
