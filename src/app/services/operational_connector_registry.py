"""Durable enrollment and health truth for vendor-neutral operational connectors."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import select

from src.app.models.orm import (
    OperationalConnectorEnrollmentRecord,
    OperationalConnectorRunRecord,
)
from src.app.services.operational_connector_contracts import (
    ConnectorNormalizationReceipt,
    OperationalConnectorEnrollment,
)


RunStatus = Literal["completed", "failed", "timed_out", "cancelled", "rejected"]


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("connector_registry_time_requires_timezone")
    return current.astimezone(timezone.utc)


def _stored_utc(value: datetime) -> datetime:
    """Normalize database timestamps; SQLite drops timezone metadata."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def enroll_operational_connector(
    db: Any,
    enrollment: OperationalConnectorEnrollment,
    *,
    reviewed_by: str,
    reviewed_at: datetime | None = None,
    commit: bool = True,
) -> OperationalConnectorEnrollmentRecord:
    """Create/update policy metadata. This never resolves or stores a credential."""

    reviewer = str(reviewed_by or "").strip()
    if not reviewer:
        raise ValueError("connector_enrollment_requires_reviewer")
    now = _utc(reviewed_at)
    row = db.execute(select(OperationalConnectorEnrollmentRecord).where(
        OperationalConnectorEnrollmentRecord.tenant_id == enrollment.tenant_id,
        OperationalConnectorEnrollmentRecord.connector_id == enrollment.connector_id,
    )).scalar_one_or_none()
    values = {
        "kind": enrollment.kind.value,
        "capability": enrollment.capability.value,
        "endpoint_origin": enrollment.endpoint_origin,
        "auth_mode": enrollment.auth_mode,
        "credential_ref": enrollment.credential_ref,
        "allowed_schema_versions_json": list(enrollment.allowed_schema_versions),
        "freshness_sla_seconds": enrollment.freshness_sla_seconds,
        "execution_mode": enrollment.execution_mode,
        "enabled": enrollment.enabled,
        "reviewed_by": reviewer,
        "reviewed_at": now,
        "updated_at": now,
    }
    if row is None:
        row = OperationalConnectorEnrollmentRecord(
            id=str(uuid.uuid4()), tenant_id=enrollment.tenant_id,
            connector_id=enrollment.connector_id, created_at=now, **values,
        )
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    if commit:
        db.commit()
    return row


def load_operational_connector(
    db: Any, *, tenant_id: str, connector_id: str,
) -> OperationalConnectorEnrollment | None:
    row = db.execute(select(OperationalConnectorEnrollmentRecord).where(
        OperationalConnectorEnrollmentRecord.tenant_id == tenant_id,
        OperationalConnectorEnrollmentRecord.connector_id == connector_id,
    )).scalar_one_or_none()
    if row is None:
        return None
    return OperationalConnectorEnrollment(
        connector_id=row.connector_id,
        tenant_id=row.tenant_id,
        kind=row.kind,
        capability=row.capability,
        endpoint_origin=row.endpoint_origin,
        auth_mode=row.auth_mode,
        credential_ref=row.credential_ref,
        allowed_schema_versions=tuple(row.allowed_schema_versions_json or []),
        freshness_sla_seconds=row.freshness_sla_seconds,
        execution_mode=row.execution_mode,
        enabled=bool(row.enabled),
    )


def record_operational_connector_run(
    db: Any,
    enrollment: OperationalConnectorEnrollment,
    *,
    run_id: str,
    status: RunStatus,
    started_at: datetime,
    completed_at: datetime,
    receipt: ConnectorNormalizationReceipt | None = None,
    latency_ms: int | None = None,
    error_code: str | None = None,
    commit: bool = True,
) -> OperationalConnectorRunRecord:
    """Append a truthful receipt; failures cannot claim observations or calls."""

    started = _utc(started_at)
    completed = _utc(completed_at)
    if completed < started:
        raise ValueError("connector_run_completed_before_start")
    if receipt and receipt.connector_id != enrollment.connector_id:
        raise ValueError("connector_run_receipt_identity_mismatch")
    if status != "completed" and receipt and receipt.normalized_count:
        raise ValueError("failed_connector_run_cannot_claim_normalized_facts")
    existing = db.execute(select(OperationalConnectorRunRecord).where(
        OperationalConnectorRunRecord.tenant_id == enrollment.tenant_id,
        OperationalConnectorRunRecord.run_id == run_id,
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    row = OperationalConnectorRunRecord(
        id=str(uuid.uuid4()), run_id=run_id, tenant_id=enrollment.tenant_id,
        connector_id=enrollment.connector_id, status=status,
        execution_mode=enrollment.execution_mode,
        source_schema_version=receipt.source_schema_version if receipt else None,
        delivery_id=receipt.delivery_id if receipt else None,
        watermark_after=receipt.watermark_after if receipt else None,
        normalized_count=receipt.normalized_count if receipt else 0,
        rejected_count=receipt.rejected_count if receipt else 0,
        external_calls=receipt.external_calls if receipt else 0,
        paid_calls=receipt.paid_calls if receipt else 0,
        latency_ms=latency_ms, error_code=error_code,
        started_at=started, completed_at=completed,
    )
    db.add(row)
    if commit:
        db.commit()
    return row


def project_operational_connector_health(
    db: Any, *, tenant_id: str, now: datetime | None = None,
) -> dict[str, Any]:
    """Separate configuration, policy readiness, observation, and live health."""

    cutoff = _utc(now)
    enrollments = db.execute(select(OperationalConnectorEnrollmentRecord).where(
        OperationalConnectorEnrollmentRecord.tenant_id == tenant_id,
    )).scalars().all()
    result = []
    for enrollment in enrollments:
        latest = db.execute(select(OperationalConnectorRunRecord).where(
            OperationalConnectorRunRecord.tenant_id == tenant_id,
            OperationalConnectorRunRecord.connector_id == enrollment.connector_id,
        ).order_by(OperationalConnectorRunRecord.completed_at.desc()).limit(1)).scalar_one_or_none()
        age_seconds = (
            max(0, int((cutoff - _stored_utc(latest.completed_at)).total_seconds()))
            if latest else None
        )
        observed_success = bool(latest and latest.status == "completed")
        fresh = bool(
            observed_success and age_seconds is not None
            and age_seconds <= enrollment.freshness_sla_seconds
        )
        policy_ready = bool(enrollment.enabled and enrollment.reviewed_by)
        live = bool(
            policy_ready and enrollment.execution_mode == "live_network"
            and latest and latest.execution_mode == "live_network"
            and latest.external_calls > 0 and fresh
        )
        result.append({
            "connector_id": enrollment.connector_id,
            "kind": enrollment.kind,
            "configured": True,
            "policy_ready": policy_ready,
            "reachable": observed_success if latest else None,
            "fresh": fresh if latest else None,
            "live": live,
            "execution_mode": enrollment.execution_mode,
            "last_status": latest.status if latest else "not_observed",
            "last_error_code": latest.error_code if latest else None,
            "last_completed_at": latest.completed_at.isoformat() if latest else None,
            "age_seconds": age_seconds,
            "external_calls": latest.external_calls if latest else 0,
            "paid_calls": latest.paid_calls if latest else 0,
            "watermark": latest.watermark_after if latest else None,
        })
    return {
        "tenant_id": tenant_id,
        "connector_count": len(result),
        "live_connector_count": sum(1 for row in result if row["live"]),
        "connectors": sorted(result, key=lambda row: row["connector_id"]),
    }


__all__ = [
    "enroll_operational_connector", "load_operational_connector",
    "project_operational_connector_health", "record_operational_connector_run",
]
