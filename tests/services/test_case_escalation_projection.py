from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.case_escalation_projection import (
    list_escalation_projections,
    project_escalation_source,
    project_existing_escalation_sources,
)


def _db() -> Session:
    db = Session(create_engine("sqlite+pysqlite:///:memory:", future=True))
    db.execute(text("""
        CREATE TABLE case_escalation (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, domain TEXT NOT NULL,
            party_ref TEXT, case_id TEXT NOT NULL, order_line_id TEXT,
            state TEXT NOT NULL, priority TEXT NOT NULL, reason_code TEXT NOT NULL,
            trigger_observation_ref TEXT, trace_id TEXT, evidence_refs_json TEXT NOT NULL,
            policy_version TEXT NOT NULL, required_response_at TEXT,
            assigned_operator_id TEXT, ticket_id TEXT, final_disposition TEXT,
            resulting_amendment_id TEXT, dedupe_key TEXT NOT NULL, version INTEGER NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(tenant_id,dedupe_key)
        )
    """))
    db.execute(text("""
        CREATE TABLE case_escalation_event (
            id TEXT PRIMARY KEY, escalation_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
            from_state TEXT, to_state TEXT NOT NULL, actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL, reason TEXT, idempotency_key TEXT NOT NULL,
            payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL,
            UNIQUE(tenant_id,idempotency_key)
        )
    """))
    db.execute(text("""
        CREATE TABLE case_escalation_projection (
            id TEXT PRIMARY KEY, escalation_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
            source_kind TEXT NOT NULL, source_id TEXT NOT NULL, source_version TEXT NOT NULL,
            projected_at TEXT NOT NULL,
            UNIQUE(tenant_id,source_kind,source_id)
        )
    """))
    db.commit()
    return db


def _project(db: Session, *, tenant: str = "tenant-a", version: str = "3"):
    return project_escalation_source(
        db,
        tenant_id=tenant,
        source_kind="procurement_room",
        source_id="room-7",
        source_version=version,
        domain="procurement",
        case_id="case-80",
        party_ref="buyer-hash",
        priority="high",
        reason_code="deadline_infeasible",
        trace_id="trace-80",
        evidence_refs=["promise/calc-80"],
        policy_version="escalation-v1",
        required_response_at="2026-08-04T05:00:00+00:00",
        actor_id="buyer-hash",
        now_iso="2026-08-04T03:00:00+00:00",
    )


def test_projection_is_idempotent_tenant_scoped_and_preserves_source_identity() -> None:
    db = _db()
    first = _project(db)
    replay = _project(db)
    other = _project(db, tenant="tenant-b")

    assert first["idempotent"] is False
    assert replay == {**first, "idempotent": True}
    assert other["escalation_id"] != first["escalation_id"]
    assert list_escalation_projections(
        db, tenant_id="tenant-a", escalation_id=first["escalation_id"]
    ) == [{
        "source_kind": "procurement_room",
        "source_id": "room-7",
        "source_version": "3",
        "projected_at": "2026-08-04T03:00:00+00:00",
    }]


def test_projection_rejects_silent_source_version_rebinding() -> None:
    db = _db()
    _project(db)
    try:
        _project(db, version="4")
    except ValueError as exc:
        assert str(exc) == "escalation_projection_version_conflict"
    else:
        raise AssertionError("version conflict must fail closed")


def test_existing_projection_skips_unowned_records_and_reports_them() -> None:
    db = _db()
    db.execute(text("""
        CREATE TABLE procurement_human_room (
            id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, version INTEGER,
            requested_at TEXT
        )
    """))
    db.execute(text("""
        CREATE TABLE tickets (
            id TEXT PRIMARY KEY, tenant_id TEXT, trace_id TEXT, severity TEXT,
            evidence TEXT, created_at TEXT, updated_at TEXT
        )
    """))
    db.execute(text(
        "INSERT INTO procurement_human_room VALUES "
        "('room-a','tenant-a','case-a',2,'2026-08-04T02:00:00+00:00')"
    ))
    db.execute(text(
        "INSERT INTO tickets VALUES "
        "('ticket-owned','tenant-a','case-a','high','{}','2026-08-04T02:01:00+00:00',NULL),"
        "('ticket-legacy',NULL,'case-x','high','{}','2026-08-04T02:02:00+00:00',NULL)"
    ))
    db.commit()

    result = project_existing_escalation_sources(
        db,
        tenant_id="tenant-a",
        actor_id="operator-1",
        now_iso="2026-08-04T03:00:00+00:00",
    )
    assert result["projected_count"] == 2
    assert result["unowned_legacy_count"] == 1
    assert result["status"] == "needs_ownership_classification"
    assert db.execute(text("SELECT COUNT(*) FROM case_escalation")).scalar_one() == 2
