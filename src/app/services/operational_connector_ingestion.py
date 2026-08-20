"""Apply enrolled connector deliveries to revisioned procurement cases."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.services.operational_connector_contracts import (
    ConnectorDelivery,
    normalize_connector_delivery,
)
from src.app.services.operational_connector_registry import (
    load_operational_connector,
    record_operational_connector_run,
)
from src.app.services.shopping_case_operational_observations import (
    record_case_operational_observation,
)


class ConnectorCaseDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(ge=1)
    delivery: ConnectorDelivery


def ingest_case_connector_delivery(
    db: Any,
    *,
    tenant_id: str,
    case_id: str,
    retained_purpose: str,
    request: ConnectorCaseDeliveryRequest,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Normalize and persist facts from a previously reviewed connector."""
    started = now or datetime.now(timezone.utc)
    if started.tzinfo is None:
        raise ValueError("connector_ingestion_time_requires_timezone")
    enrollment = load_operational_connector(
        db, tenant_id=tenant_id, connector_id=request.delivery.connector_id,
    )
    if enrollment is None:
        raise ValueError("operational_connector_not_enrolled")
    observations, receipt = normalize_connector_delivery(
        enrollment, request.delivery, expected_revision=request.expected_revision,
    )
    if not observations:
        completed = datetime.now(timezone.utc)
        record_operational_connector_run(
            db, enrollment,
            run_id=f"delivery:{request.delivery.delivery_id}",
            status="rejected", started_at=started, completed_at=completed,
            error_code="connector_delivery_no_valid_facts",
        )
        raise ValueError("connector_delivery_no_valid_facts")

    results: list[dict[str, Any]] = []
    try:
        for observation in observations:
            results.append(record_case_operational_observation(
                db,
                tenant_id=tenant_id,
                case_id=case_id,
                retained_purpose=retained_purpose,
                observation=observation,
                deployment_id=f"operational_connector:{enrollment.connector_id}",
                ingestion_mode=f"enrolled_connector:{enrollment.execution_mode}",
            ))
    except Exception:
        record_operational_connector_run(
            db, enrollment,
            run_id=f"delivery:{request.delivery.delivery_id}",
            status="failed", started_at=started,
            completed_at=datetime.now(timezone.utc),
            error_code="connector_observation_persistence_failed",
        )
        raise

    completed = datetime.now(timezone.utc)
    run = record_operational_connector_run(
        db, enrollment,
        run_id=f"delivery:{request.delivery.delivery_id}",
        status="completed", started_at=started, completed_at=completed,
        receipt=receipt,
        latency_ms=max(0, int((completed - started).total_seconds() * 1000)),
    )
    return {
        "schema_version": "case-connector-ingestion-v1",
        "case_id": case_id,
        "connector_id": enrollment.connector_id,
        "connector_kind": enrollment.kind.value,
        "execution_mode": enrollment.execution_mode,
        "delivery_id": request.delivery.delivery_id,
        "connector_run_id": run.run_id,
        "normalization_receipt": receipt.model_dump(mode="json"),
        "observations": results,
        "starting_revision": request.expected_revision,
        "ending_revision": int(results[-1]["case_revision"]),
        "commercial_authority_granted": False,
        "cart_mutations": sum(int(row.get("cart_mutations") or 0) for row in results),
        "supplier_sends": 0,
    }


__all__ = ["ConnectorCaseDeliveryRequest", "ingest_case_connector_delivery"]
