from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.models.orm import Base
from src.app.services.operational_connector_contracts import (
    ConnectorNormalizationReceipt,
    OperationalConnectorEnrollment,
)
from src.app.services.operational_connector_registry import (
    enroll_operational_connector,
    project_operational_connector_health,
    record_operational_connector_run,
)


NOW = datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _enrollment(mode="certification_fixture"):
    live = mode == "live_network"
    return OperationalConnectorEnrollment(
        connector_id=f"price-{mode}", tenant_id="portfolio", kind="retailer_price",
        capability="forecast_observation_read",
        endpoint_origin="https://price.example" if live else "http://127.0.0.1:9999",
        auth_mode="api_key" if live else "none",
        credential_ref="secret://pilot/price" if live else None,
        allowed_schema_versions=("v1",), freshness_sla_seconds=300,
        execution_mode=mode, enabled=True,
    )


def _receipt(enrollment, external_calls):
    return ConnectorNormalizationReceipt(
        connector_id=enrollment.connector_id, connector_kind=enrollment.kind,
        execution_mode=enrollment.execution_mode, source_schema_version="v1",
        delivery_id="delivery-0001", normalized_count=2, rejected_count=0,
        watermark_before="10", watermark_after="11", external_calls=external_calls,
    )


def test_fixture_is_configured_and_fresh_but_never_live():
    db = _db()
    enrollment = _enrollment()
    enroll_operational_connector(db, enrollment, reviewed_by="portfolio-owner", reviewed_at=NOW)
    record_operational_connector_run(
        db, enrollment, run_id="run-fixture-001", status="completed",
        receipt=_receipt(enrollment, 0), started_at=NOW,
        completed_at=NOW + timedelta(milliseconds=10), latency_ms=10,
    )
    row = project_operational_connector_health(db, tenant_id="portfolio", now=NOW)[
        "connectors"
    ][0]
    assert row["configured"] is row["policy_ready"] is row["reachable"] is True
    assert row["fresh"] is True
    assert row["live"] is False
    assert row["external_calls"] == row["paid_calls"] == 0


def test_live_requires_observed_network_call_and_becomes_stale():
    db = _db()
    enrollment = _enrollment("live_network")
    enroll_operational_connector(db, enrollment, reviewed_by="connector-owner", reviewed_at=NOW)
    record_operational_connector_run(
        db, enrollment, run_id="run-live-0001", status="completed",
        receipt=_receipt(enrollment, 1), started_at=NOW,
        completed_at=NOW + timedelta(seconds=1), latency_ms=1000,
    )
    current = project_operational_connector_health(
        db, tenant_id="portfolio", now=NOW + timedelta(seconds=60),
    )["connectors"][0]
    stale = project_operational_connector_health(
        db, tenant_id="portfolio", now=NOW + timedelta(seconds=601),
    )["connectors"][0]
    assert current["live"] is True and current["paid_calls"] == 0
    assert stale["fresh"] is stale["live"] is False


def test_failed_run_is_reachable_false_and_idempotent():
    db = _db()
    enrollment = _enrollment("live_network")
    enroll_operational_connector(db, enrollment, reviewed_by="connector-owner", reviewed_at=NOW)
    first = record_operational_connector_run(
        db, enrollment, run_id="run-failed-001", status="timed_out",
        started_at=NOW, completed_at=NOW + timedelta(seconds=2),
        error_code="connector_deadline_exceeded",
    )
    replay = record_operational_connector_run(
        db, enrollment, run_id="run-failed-001", status="timed_out",
        started_at=NOW, completed_at=NOW + timedelta(seconds=2),
    )
    assert replay.id == first.id
    row = project_operational_connector_health(db, tenant_id="portfolio", now=NOW)[
        "connectors"
    ][0]
    assert row["reachable"] is False and row["live"] is False
    assert row["last_error_code"] == "connector_deadline_exceeded"
