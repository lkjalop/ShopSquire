"""Vertical decision-run boundary over the existing recommendation pipeline.

This adapter is deliberately observational while the legacy core is strangled:
it binds every evaluated response to the effective procurement case revision,
records typed stage receipts, and grants no commercial authority.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.app.services.procurement_case_state import ProcurementCaseState
from src.app.services.procurement_decision_run import (
    InvalidationReason, StageReceipt, create_decision_run,
    create_decision_snapshot, persist_decision_run,
)
from src.app.services.temporal_conflicts import TemporalClaim, detect_temporal_conflicts

logger = logging.getLogger("shopsquire.procurement_decision")


class ProcurementDecisionCoordinator:
    """Own one shadow vertical while the legacy core remains its stage implementation.

    The coordinator owns invocation, cancellation checkpoints, timing truth and
    immutable run persistence. It grants no commercial authority and does not
    reinterpret the legacy result.
    """

    def __init__(self, db: Any, envelope: Any) -> None:
        self.db = db
        self.envelope = envelope

    def evaluate(self, execute: Callable[[], Any]) -> Any:
        cancellation = getattr(self.envelope, "cancellation", None)
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        started = time.perf_counter()
        response = execute()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if cancellation is not None:
            cancellation.raise_if_cancelled()
        try:
            deadline_ms = max(100, min(int(os.getenv(
                "PROCUREMENT_DECISION_SHADOW_DEADLINE_MS", "30000",
            )), 120_000))
        except (TypeError, ValueError):
            deadline_ms = 30_000
        response.extras["procurement_decision_coordinator"] = {
            "schema_version": "procurement-decision-coordinator-shadow-v1",
            "mode": "shadow_owner_legacy_stage_adapter",
            "elapsed_ms": round(elapsed_ms, 1),
            "deadline_ms": deadline_ms,
            "deadline_status": "exceeded_observed" if elapsed_ms > deadline_ms else "within_deadline",
            "buyer_visible_authority": False,
            "commercial_authority_granted": False,
        }
        return response

    def persist(self, response: Any) -> None:
        record_procurement_decision_run_safely(
            self.db, envelope=self.envelope, response=response,
        )


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str,
    ).encode()).hexdigest()


_INVALIDATION_STAGES = {
    "objective": ("interpretation", "evidence", "fit", "commercial", "response"),
    "workloads": ("interpretation", "evidence", "fit", "commercial", "response"),
    "requirements": ("evidence", "fit", "commercial", "response"),
    "selected_sku": ("fit", "commercial", "fulfilment", "response"),
    "candidate_skus": ("fit", "commercial", "fulfilment", "response"),
    "requested_quantity": ("commercial", "fulfilment", "response"),
    "destinations": ("commercial", "fulfilment", "response"),
    "temporal": ("commercial", "fulfilment", "response"),
    "budget": ("commercial", "response"),
    "research": ("evidence", "fit", "response"),
    "fulfilment": ("commercial", "fulfilment", "response"),
    "policies": ("interpretation", "evidence", "fit", "commercial", "fulfilment", "response"),
}

_STAGE_INPUTS: dict[str, tuple[str, ...]] = {
    "interpretation": ("buyer:outcome", "case:constraints"),
    "evidence": ("interpretation:hypotheses", "evidence:watermarks"),
    "catalog_retrieval": ("interpretation:hypotheses", "catalog:exact"),
    "fit": ("requirements:accepted", "catalog:exact"),
    "commercial": ("fit:verdicts", "inventory:current", "price:current"),
    "fulfilment": ("commercial:shelves", "supplier:offers", "delivery:observations"),
    "response": ("fit:verdicts", "commercial:shelves", "fulfilment:options"),
}


def _artifact_refs(stage: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    key = str(stage).casefold().replace("-", "_").replace(" ", "_")
    inputs = _STAGE_INPUTS.get(key, ("case:state",))
    output = (f"{key}:output",)
    return inputs, output


def invalidations_for_changed_paths(paths: list[str] | tuple[str, ...]) -> tuple[InvalidationReason, ...]:
    rows: list[InvalidationReason] = []
    for path in dict.fromkeys(str(item) for item in paths if str(item)):
        root = path.split(".", 1)[0]
        stages = _INVALIDATION_STAGES.get(root, ("response",))
        rows.append(InvalidationReason(
            code="case_state_changed", changed_path=path, invalidated_stages=stages,
        ))
    return tuple(rows)


def record_procurement_decision_run(db, *, envelope: Any, response: Any) -> dict[str, Any] | None:
    """Persist one immutable observation of an existing core evaluation."""
    raw = response.extras.get("procurement_case_state")
    if not isinstance(raw, dict):
        raw = (envelope.session or {}).get("procurement_case_state")
    if not isinstance(raw, dict):
        return None
    state = ProcurementCaseState.model_validate(raw)
    now = datetime.now(timezone.utc)
    evaluation_time = now
    if state.temporal and state.temporal.required_by:
        evaluation_time = datetime.fromisoformat(
            state.temporal.required_by.replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    snapshot = create_decision_snapshot(
        state, tenant_id=envelope.tenant_id, knowledge_cutoff=now,
        evaluation_time=evaluation_time,
        catalog_snapshot_id=str(response.extras.get("catalog_snapshot_id") or "") or None,
        market_snapshot_id=str(response.extras.get("market_snapshot_id") or "") or None,
        policy_snapshot_id=str(response.extras.get("policy_snapshot_id") or "") or None,
    )
    receipts: list[StageReceipt] = []
    for index, item in enumerate(response.stage_results):
        latency = max(0.0, float(getattr(item, "latency_ms", 0.0) or 0.0))
        started = now - timedelta(milliseconds=latency)
        raw_status = str(getattr(item, "status", "ok") or "ok").lower()
        if raw_status == "ok":
            status = "completed"
        elif raw_status == "skipped":
            status = "not_run"
        elif raw_status in {"cancelled", "canceled"}:
            status = "cancelled"
        elif raw_status in {"failed", "error"}:
            status = "failed"
        else:
            status = "degraded"
        output = item.as_dict()
        stage = str(item.stage)
        stage_id = str(getattr(item, "stage_id", "") or (
            f"stage-{index:02d}-{stage.casefold().replace('_', '-')}"
        ))
        emitted_inputs = tuple(getattr(item, "input_artifact_refs", ()) or ())
        emitted_outputs = tuple(getattr(item, "output_artifact_refs", ()) or ())
        emitted_dependencies = tuple(getattr(item, "dependency_stage_ids", ()) or ())
        fallback_inputs, fallback_outputs = _artifact_refs(stage)
        input_refs = emitted_inputs or fallback_inputs
        output_refs = emitted_outputs or fallback_outputs
        receipts.append(StageReceipt(
            stage=stage, stage_id=stage_id, status=status,
            started_at=started.isoformat(), completed_at=now.isoformat(),
            input_hash=snapshot.state_hash,
            output_hash=_digest(output) if status == "completed" else None,
            reason_code=None if status == "completed" else f"legacy_stage_{raw_status}",
            dependency_stages=(receipts[-1].stage,) if receipts else (),
            input_artifact_refs=input_refs,
            output_artifact_refs=output_refs,
            dependency_stage_ids=(
                emitted_dependencies
                or ((receipts[-1].stage_id,) if receipts else ())
            ),
        ))
    application = response.extras.get("case_patch_application")
    changed = list(application.get("changed_paths") or []) if isinstance(application, dict) else []
    raw_claims = response.extras.get("temporal_claims")
    temporal_claims: list[TemporalClaim] = []
    if isinstance(raw_claims, list):
        for raw_claim in raw_claims[:128]:
            if isinstance(raw_claim, dict):
                temporal_claims.append(TemporalClaim.model_validate(raw_claim))
    conflicts = detect_temporal_conflicts(temporal_claims)
    run = create_decision_run(
        snapshot,
        idempotency_key=f"recommendation:{envelope.trace_id}",
        status="degraded" if response.degraded else "completed",
        stage_receipts=tuple(receipts),
        invalidations=invalidations_for_changed_paths(changed),
        temporal_conflicts=conflicts,
        now=now,
    )
    persisted = persist_decision_run(db, run)
    projection = {
        "run_id": persisted.run_id,
        "case_id": snapshot.case_id,
        "case_revision": snapshot.case_revision,
        "knowledge_cutoff": snapshot.knowledge_cutoff,
        "evaluation_time": snapshot.evaluation_time,
        "status": persisted.status,
        "stage_count": len(persisted.stage_receipts),
        "stage_receipts": [
            {
                "stage": item.stage,
                "status": item.status,
                "dependency_stages": list(item.dependency_stages),
                "reason_code": item.reason_code,
            }
            for item in persisted.stage_receipts
        ],
        "invalidations": [item.model_dump(mode="json") for item in persisted.invalidations],
        "temporal_conflicts": [
            item.model_dump(mode="json") for item in persisted.temporal_conflicts
        ],
        "evidence_watermarks": [
            item.model_dump(mode="json") for item in snapshot.evidence_watermarks
        ],
        "state_hash": snapshot.state_hash,
        "persistence_status": "persisted",
        "commercial_authority_granted": False,
    }
    response.extras["procurement_decision_run"] = projection
    return projection


def record_procurement_decision_run_safely(db, *, envelope: Any, response: Any) -> None:
    try:
        record_procurement_decision_run(db, envelope=envelope, response=response)
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            logger.exception("procurement decision run rollback failed")
        logger.exception("procurement decision run persistence failed: %s", exc)
        response.extras["procurement_decision_run"] = {
            "persistence_status": "failed",
            "error_code": "decision_run_persistence_failed",
            "commercial_authority_granted": False,
        }


__all__ = [
    "ProcurementDecisionCoordinator",
    "invalidations_for_changed_paths", "record_procurement_decision_run",
    "record_procurement_decision_run_safely",
]
