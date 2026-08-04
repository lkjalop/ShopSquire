from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import Boolean, Column, Integer, MetaData, Table, Text, create_engine, text
from sqlalchemy.orm import Session

from src.app.services.promise_feasibility import evaluate_promise_feasibility
from src.app.services.temporal_authority import (
    CalendarException,
    OperationalCalendar,
    OperationalInterval,
    ResponsePolicy,
)
from src.app.services.temporal_authority_repository import (
    persist_operational_calendar,
    persist_supplier_response_policy,
    record_promise_calculation,
    record_temporal_expectation,
    supplier_response_expectation,
    supersede_case_promise_calculations,
)


def _table(metadata, name, *columns):
    return Table(name, metadata, *columns)


def _db() -> Session:
    metadata = MetaData()
    _table(metadata, "operational_calendar",
           Column("id", Text, primary_key=True), Column("tenant_id", Text), Column("owner_type", Text),
           Column("owner_ref", Text), Column("timezone_name", Text), Column("calendar_version", Text),
           Column("authority", Text), Column("source_ref", Text), Column("source_version", Text),
           Column("observed_at", Text), Column("expires_at", Text), Column("effective_from", Text),
           Column("status", Text), Column("created_at", Text))
    _table(metadata, "operational_calendar_interval",
           Column("id", Text, primary_key=True), Column("calendar_id", Text), Column("weekday", Integer),
           Column("start_local", Text), Column("end_local", Text))
    _table(metadata, "operational_calendar_exception",
           Column("id", Text, primary_key=True), Column("calendar_id", Text), Column("local_date", Text),
           Column("closed", Boolean), Column("intervals_json", Text), Column("reason", Text))
    _table(metadata, "supplier_response_policy",
           Column("id", Text, primary_key=True), Column("tenant_id", Text), Column("supplier_id", Text),
           Column("supplier_facility_id", Text), Column("channel", Text), Column("calendar_id", Text),
           Column("policy_version", Text), Column("acknowledgement_business_seconds", Integer),
           Column("quote_business_seconds", Integer), Column("human_decision_business_seconds", Integer),
           Column("transmit_outside_hours", Boolean), Column("effective_from", Text), Column("status", Text),
           Column("created_at", Text))
    _table(metadata, "temporal_expectation",
           Column("id", Text, primary_key=True), Column("tenant_id", Text), Column("subject_type", Text),
           Column("subject_id", Text), Column("channel", Text), Column("calendar_id", Text),
           Column("calendar_version", Text), Column("policy_version", Text), Column("submitted_at", Text),
           Column("calendar_state", Text), Column("sla_clock", Text), Column("transmission_state", Text),
           Column("next_open_at", Text), Column("acknowledgement_due_at", Text), Column("quote_due_at", Text),
           Column("human_decision_due_at", Text), Column("dependencies_json", Text), Column("status", Text),
           Column("calculated_at", Text))
    _table(metadata, "promise_calculation",
           Column("id", Text, primary_key=True), Column("tenant_id", Text), Column("case_id", Text),
           Column("option_id", Text), Column("calculation_version", Text), Column("requested_quantity", Integer),
           Column("requested_arrival_at", Text), Column("feasibility", Text), Column("confirmed_quantity", Integer),
           Column("unknown_quantity", Integer), Column("quantity_by_deadline", Integer),
           Column("latest_viable_response_at", Text), Column("earliest_arrival_at", Text),
           Column("latest_arrival_at", Text), Column("carrier_cutoff_at", Text),
           Column("dispatch_ready_at", Text), Column("evaluated_at", Text),
           Column("response_expectation_json", Text),
           Column("reason_codes_json", Text), Column("dependencies_json", Text), Column("status", Text),
           Column("calculated_at", Text))
    _table(metadata, "promise_dependency",
           Column("id", Text, primary_key=True), Column("promise_calculation_id", Text),
           Column("dependency_type", Text), Column("dependency_id", Text),
           Column("dependency_version", Text), Column("observed_at", Text),
           Column("effective_at", Text), Column("created_at", Text))
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    metadata.create_all(engine)
    return Session(engine)


def _calendar(*, freshness="current") -> OperationalCalendar:
    return OperationalCalendar(
        calendar_id="SUP-1-MEL", owner_type="supplier_facility", owner_ref="FAC-MEL",
        timezone_name="Australia/Melbourne",
        weekly_intervals=tuple(
            OperationalInterval(weekday=weekday, start_local=time(9), end_local=time(17))
            for weekday in range(5)
        ),
        exceptions=(CalendarException(local_date=date(2026, 8, 10), closed=True),),
        version="calendar-v3", authority="supplier_onboarding", freshness=freshness,
    )


def test_calendar_policy_expectation_round_trip_and_idempotency():
    db = _db()
    calendar_result = persist_operational_calendar(
        db, tenant_id="tenant-a", calendar=_calendar(), source_ref="onboarding:SUP-1",
        source_version="form-7", observed_at="2026-08-01T00:00:00Z",
        expires_at="2026-09-01T00:00:00Z", effective_from="2026-08-01T00:00:00Z",
    )
    policy = ResponsePolicy(
        version="response-v2", acknowledgement_business_seconds=7200,
        quote_business_seconds=21600, human_decision_business_seconds=3600,
        transmit_outside_hours=False,
    )
    persist_supplier_response_policy(
        db, tenant_id="tenant-a", supplier_id="SUP-1", supplier_facility_id="FAC-MEL",
        channel="email", calendar_id=calendar_result["id"], policy=policy,
        effective_from="2026-08-01T00:00:00Z",
    )
    db.commit()

    expectation = supplier_response_expectation(
        db, tenant_id="tenant-a", supplier_id="SUP-1", supplier_facility_id="FAC-MEL",
        submitted_at=datetime(2026, 8, 9, 23, 0, tzinfo=timezone.utc),
    )
    assert expectation["calendar_state"] == "closed"
    assert expectation["sla_clock"] == "paused"
    assert expectation["next_open_at"] == "2026-08-10T23:00:00+00:00"
    assert expectation["calendar_version"] == "calendar-v3"
    assert expectation["policy_version"] == "response-v2"

    first = record_temporal_expectation(
        db, tenant_id="tenant-a", subject_type="rfq", subject_id="RFQ-7", channel="email",
        submitted_at="2026-08-09T23:00:00Z", expectation=expectation,
    )
    second = record_temporal_expectation(
        db, tenant_id="tenant-a", subject_type="rfq", subject_id="RFQ-7", channel="email",
        submitted_at="2026-08-09T23:00:00Z", expectation=expectation,
    )
    assert first["id"] == second["id"]
    assert second["idempotent"] is True
    assert db.execute(text("SELECT COUNT(*) FROM temporal_expectation")).scalar_one() == 1


def test_promise_calculation_persists_exact_dependencies_and_unknown_state():
    db = _db()
    result = evaluate_promise_feasibility(
        requested_quantity=80, requested_arrival_at="2026-08-14T17:00:00+10:00",
        evaluated_at="2026-08-04T09:00:00+10:00",
        supply_lines=[
            {"source_ref": "network", "quantity": 53, "status": "confirmed",
             "arrival_min": "2026-08-05T09:00:00+10:00", "arrival_max": "2026-08-06T17:00:00+10:00"},
            {"source_ref": "supplier", "quantity": 27, "status": "unconfirmed"},
        ],
        dependency_versions={"atp": "snapshot-8", "calendar": "calendar-v3"},
    )
    stored = record_promise_calculation(
        db, tenant_id="tenant-a", case_id="case-80", option_id="ship-together", result=result,
    )
    row = db.execute(text(
        "SELECT feasibility,confirmed_quantity,unknown_quantity,dependencies_json "
        "FROM promise_calculation WHERE id=:id"
    ), {"id": stored["id"]}).one()
    assert row[0] == "unknown"
    assert row[1] == 53
    assert row[2] == 27
    assert '"atp":"snapshot-8"' in row[3]
    dependencies = db.execute(text(
        "SELECT dependency_type,dependency_version FROM promise_dependency ORDER BY dependency_type"
    )).all()
    assert dependencies == [("atp", "snapshot-8"), ("calendar", "calendar-v3")]


def test_amendment_supersedes_but_retains_historical_promise_calculation():
    db = _db()
    result = evaluate_promise_feasibility(
        requested_quantity=10, requested_arrival_at="2026-08-14T17:00:00+10:00",
        evaluated_at="2026-08-04T09:00:00+10:00",
        supply_lines=[{"source_ref": "network", "quantity": 10, "status": "confirmed",
                       "arrival_min": "2026-08-05T09:00:00+10:00",
                       "arrival_max": "2026-08-05T17:00:00+10:00"}],
        dependency_versions={"atp": "snapshot-8"},
    )
    record_promise_calculation(
        db, tenant_id="tenant-a", case_id="case-amend", option_id="ship", result=result,
    )
    superseded = supersede_case_promise_calculations(
        db, tenant_id="tenant-a", case_id="case-amend", reason="destination_changed",
    )
    assert superseded["superseded"] == 1
    assert db.execute(text(
        "SELECT status FROM promise_calculation WHERE case_id='case-amend'"
    )).scalar_one() == "superseded"
