"""Vertical decision-run boundary over the existing recommendation pipeline.

This adapter is deliberately observational while the legacy core is strangled:
it binds every evaluated response to the effective procurement case revision,
records typed stage receipts, and grants no commercial authority.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.app.services.procurement_case_state import ProcurementCaseState
from src.app.services.procurement_decision_run import (
    InvalidationReason, StageReceipt, create_decision_run,
    create_decision_snapshot, persist_decision_run,
)

logger = logging.getLogger("shopsquire.procurement_decision")


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
    for item in response.stage_results:
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
        receipts.append(StageReceipt(
            stage=str(item.stage), status=status,
            started_at=started.isoformat(), completed_at=now.isoformat(),
            input_hash=snapshot.state_hash,
            output_hash=_digest(output) if status == "completed" else None,
            reason_code=None if status == "completed" else f"legacy_stage_{raw_status}",
            dependency_stages=(receipts[-1].stage,) if receipts else (),
        ))
    application = response.extras.get("case_patch_application")
    changed = list(application.get("changed_paths") or []) if isinstance(application, dict) else []
    run = create_decision_run(
        snapshot,
        idempotency_key=f"recommendation:{envelope.trace_id}",
        status="degraded" if response.degraded else "completed",
        stage_receipts=tuple(receipts),
        invalidations=invalidations_for_changed_paths(changed),
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
        logger.exception("procurement decision run persistence failed: %s", exc)
        response.extras["procurement_decision_run"] = {
            "persistence_status": "failed",
            "error_code": "decision_run_persistence_failed",
            "commercial_authority_granted": False,
        }


__all__ = [
    "invalidations_for_changed_paths", "record_procurement_decision_run",
    "record_procurement_decision_run_safely",
]
