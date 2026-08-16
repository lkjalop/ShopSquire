"""Immutable, revision-bound procurement decision snapshots and run receipts."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from src.app.models.orm import ProcurementDecisionRunRecord
from src.app.services.procurement_case_state import ProcurementCaseState


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("decision_time_requires_timezone")
    return parsed.astimezone(timezone.utc)


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class StageStatus(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NOT_RUN = "not_run"


class EvidenceWatermark(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1, max_length=160)
    observed_at: str
    source_version: str | None = Field(default=None, max_length=160)
    content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    state: Literal["current", "stale", "unavailable", "empty", "undisclosed"]

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: str) -> str:
        _utc(value)
        return value


class InvalidationReason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=120)
    changed_path: str = Field(min_length=1, max_length=200)
    invalidated_stages: tuple[str, ...] = Field(min_length=1, max_length=16)
    evidence_ref: str | None = Field(default=None, max_length=240)


class StageReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str = Field(min_length=1, max_length=80)
    status: StageStatus
    started_at: str
    completed_at: str
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    output_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason_code: str | None = Field(default=None, max_length=160)
    dependency_stages: tuple[str, ...] = Field(default_factory=tuple, max_length=16)

    @model_validator(mode="after")
    def validate_timing_and_output(self) -> "StageReceipt":
        if _utc(self.completed_at) < _utc(self.started_at):
            raise ValueError("stage_completed_before_start")
        if self.status == StageStatus.COMPLETED and self.output_hash is None:
            raise ValueError("completed_stage_requires_output_hash")
        if self.status != StageStatus.COMPLETED and not self.reason_code:
            raise ValueError("noncompleted_stage_requires_reason")
        return self


class ProcurementDecisionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["procurement-decision-snapshot-v1"] = (
        "procurement-decision-snapshot-v1"
    )
    tenant_id: str = Field(min_length=1, max_length=200)
    case_id: str = Field(min_length=1, max_length=200)
    case_revision: int = Field(ge=1)
    knowledge_cutoff: str
    evaluation_time: str
    case_state: ProcurementCaseState
    state_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    evidence_watermarks: tuple[EvidenceWatermark, ...] = ()
    catalog_snapshot_id: str | None = Field(default=None, max_length=200)
    market_snapshot_id: str | None = Field(default=None, max_length=200)
    policy_snapshot_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_snapshot(self) -> "ProcurementDecisionSnapshot":
        _utc(self.knowledge_cutoff)
        _utc(self.evaluation_time)
        if self.case_state.case_id != self.case_id:
            raise ValueError("snapshot_case_id_mismatch")
        if self.case_state.revision != self.case_revision:
            raise ValueError("snapshot_case_revision_mismatch")
        expected = _digest(self.case_state.model_dump(mode="json"))
        if self.state_hash != expected:
            raise ValueError("snapshot_state_hash_mismatch")
        return self


class DecisionRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["procurement-decision-run-v1"] = "procurement-decision-run-v1"
    run_id: str = Field(min_length=8, max_length=100)
    idempotency_key: str = Field(min_length=1, max_length=200)
    snapshot: ProcurementDecisionSnapshot
    status: Literal["completed", "degraded", "failed", "cancelled"]
    stage_receipts: tuple[StageReceipt, ...] = ()
    invalidations: tuple[InvalidationReason, ...] = ()
    created_at: str
    completed_at: str
    commercial_authority_granted: Literal[False] = False

    @model_validator(mode="after")
    def validate_run(self) -> "DecisionRun":
        if _utc(self.completed_at) < _utc(self.created_at):
            raise ValueError("decision_run_completed_before_created")
        stage_names = [receipt.stage for receipt in self.stage_receipts]
        if len(stage_names) != len(set(stage_names)):
            raise ValueError("duplicate_stage_receipt")
        return self


def create_decision_snapshot(
    state: ProcurementCaseState,
    *,
    tenant_id: str,
    knowledge_cutoff: datetime | None = None,
    evaluation_time: datetime | None = None,
    evidence_watermarks: tuple[EvidenceWatermark, ...] = (),
    catalog_snapshot_id: str | None = None,
    market_snapshot_id: str | None = None,
    policy_snapshot_id: str | None = None,
) -> ProcurementDecisionSnapshot:
    known = (knowledge_cutoff or datetime.now(timezone.utc)).astimezone(timezone.utc)
    effective = (evaluation_time or known).astimezone(timezone.utc)
    state_json = state.model_dump(mode="json")
    return ProcurementDecisionSnapshot(
        tenant_id=tenant_id,
        case_id=state.case_id,
        case_revision=state.revision,
        knowledge_cutoff=known.isoformat(),
        evaluation_time=effective.isoformat(),
        case_state=state,
        state_hash=_digest(state_json),
        evidence_watermarks=evidence_watermarks,
        catalog_snapshot_id=catalog_snapshot_id,
        market_snapshot_id=market_snapshot_id,
        policy_snapshot_id=policy_snapshot_id,
    )


def create_decision_run(
    snapshot: ProcurementDecisionSnapshot,
    *,
    idempotency_key: str,
    status: Literal["completed", "degraded", "failed", "cancelled"],
    stage_receipts: tuple[StageReceipt, ...] = (),
    invalidations: tuple[InvalidationReason, ...] = (),
    now: datetime | None = None,
) -> DecisionRun:
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    stable = _digest({
        "tenant_id": snapshot.tenant_id,
        "case_id": snapshot.case_id,
        "case_revision": snapshot.case_revision,
        "idempotency_key": idempotency_key,
    })[:24]
    return DecisionRun(
        run_id=f"pdr-{stable}",
        idempotency_key=idempotency_key,
        snapshot=snapshot,
        status=status,
        stage_receipts=stage_receipts,
        invalidations=invalidations,
        created_at=timestamp,
        completed_at=timestamp,
    )


def persist_decision_run(db, run: DecisionRun) -> DecisionRun:
    """Append one immutable run, returning the prior identical retry if present."""
    snapshot = run.snapshot
    existing = db.execute(select(ProcurementDecisionRunRecord).where(
        ProcurementDecisionRunRecord.tenant_id == snapshot.tenant_id,
        ProcurementDecisionRunRecord.case_id == snapshot.case_id,
        ProcurementDecisionRunRecord.idempotency_key == run.idempotency_key,
    )).scalar_one_or_none()
    payload = run.model_dump(mode="json")
    payload_hash = _digest(payload)
    if existing is not None:
        if (
            existing.case_revision != snapshot.case_revision
            or existing.state_hash != snapshot.state_hash
        ):
            raise ValueError("decision_run_idempotency_conflict")
        return DecisionRun.model_validate(existing.payload_json)
    db.add(ProcurementDecisionRunRecord(
        id=str(uuid.uuid4()), run_id=run.run_id,
        tenant_id=snapshot.tenant_id, case_id=snapshot.case_id,
        case_revision=snapshot.case_revision,
        idempotency_key=run.idempotency_key,
        knowledge_cutoff=_utc(snapshot.knowledge_cutoff),
        evaluation_time=_utc(snapshot.evaluation_time),
        status=run.status, state_hash=snapshot.state_hash,
        payload_hash=payload_hash, payload_json=payload,
        created_at=_utc(run.created_at),
    ))
    db.commit()
    return run


def load_decision_runs(db, *, tenant_id: str, case_id: str) -> list[DecisionRun]:
    rows = db.execute(select(ProcurementDecisionRunRecord).where(
        ProcurementDecisionRunRecord.tenant_id == tenant_id,
        ProcurementDecisionRunRecord.case_id == case_id,
    ).order_by(
        ProcurementDecisionRunRecord.case_revision.asc(),
        ProcurementDecisionRunRecord.created_at.asc(),
    )).scalars().all()
    return [DecisionRun.model_validate(row.payload_json) for row in rows]


__all__ = [
    "DecisionRun", "EvidenceWatermark", "InvalidationReason",
    "ProcurementDecisionSnapshot", "StageReceipt", "StageStatus",
    "create_decision_run", "create_decision_snapshot", "load_decision_runs",
    "persist_decision_run",
]
