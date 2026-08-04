import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.conversation_case_state import (
    apply_case_amendment,
    classify_case_turn,
    ensure_case_state,
    get_case_state,
    record_case_turn,
)


def _db() -> Session:
    db = Session(create_engine("sqlite+pysqlite:///:memory:", future=True))
    db.execute(text("""
        CREATE TABLE conversation_case_state (
            id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT NOT NULL,
            session_epoch TEXT NOT NULL, subject_ref TEXT NOT NULL, version INTEGER NOT NULL,
            state_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE(tenant_id, case_id, session_epoch)
        )
    """))
    db.execute(text("""
        CREATE TABLE conversation_case_amendment (
            id TEXT PRIMARY KEY, case_state_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
            case_id TEXT NOT NULL, session_epoch TEXT NOT NULL, source_message_id TEXT NOT NULL,
            trace_id TEXT, dialogue_act TEXT NOT NULL, field_name TEXT, old_value_json TEXT,
            proposed_value_json TEXT, confidence REAL NOT NULL, risk TEXT NOT NULL,
            requires_confirmation INTEGER NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL,
            provenance_json TEXT NOT NULL, supersedes_id TEXT, observed_at TEXT NOT NULL,
            effective_at TEXT, created_at TEXT NOT NULL,
            UNIQUE(tenant_id, session_epoch, source_message_id, dialogue_act, field_name)
        )
    """))
    db.commit()
    return db


def _seed(db: Session, *, tenant: str = "tenant-a", epoch: str = "epoch-1") -> None:
    ensure_case_state(
        db,
        tenant_id=tenant,
        case_id="case-1",
        session_epoch=epoch,
        subject_ref="buyer-hash",
        authoritative_anchor={
            "sku": "RGAM-0007",
            "quantity": 40,
            "destination": "Sydney",
            "budget": {"amount": 200000, "currency": "AUD", "scope": "total"},
        },
        now_iso="2026-08-04T01:00:00+00:00",
    )


def test_status_and_summary_read_case_without_proposing_a_mutation() -> None:
    db = _db()
    _seed(db)

    result = record_case_turn(
        db,
        tenant_id="tenant-a",
        case_id="case-1",
        session_epoch="epoch-1",
        subject_ref="buyer-hash",
        source_message_id="message-status",
        message="What is the status of my order?",
    )

    assert result["dialogue_act"] == "request_status"
    assert result["state_changed"] is False
    assert result["retrieval_required"] is False
    assert db.execute(text("SELECT COUNT(*) FROM conversation_case_amendment")).scalar_one() == 1
    assert get_case_state(db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1")["sku"] == "RGAM-0007"


def test_destination_is_an_amendment_and_never_changes_product_identity() -> None:
    db = _db()
    _seed(db)

    result = record_case_turn(
        db,
        tenant_id="tenant-a",
        case_id="case-1",
        session_epoch="epoch-1",
        subject_ref="buyer-hash",
        source_message_id="message-destination",
        message="Actually send them to Parramatta.",
    )

    assert result["dialogue_act"] == "amend_destination"
    assert result["status"] == "accepted"
    state = get_case_state(db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1")
    assert state["destination"] == "Parramatta"
    assert state["sku"] == "RGAM-0007"


def test_quantity_change_is_pending_until_explicit_confirmation() -> None:
    db = _db()
    _seed(db)
    result = record_case_turn(
        db,
        tenant_id="tenant-a",
        case_id="case-1",
        session_epoch="epoch-1",
        subject_ref="buyer-hash",
        source_message_id="message-quantity",
        message="Increase the quantity to 80.",
    )

    assert result["dialogue_act"] == "amend_quantity"
    assert result["status"] == "pending_confirmation"
    assert result["state_changed"] is False
    assert get_case_state(db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1")["quantity"] == 40

    applied = apply_case_amendment(
        db,
        tenant_id="tenant-a",
        case_id="case-1",
        session_epoch="epoch-1",
        amendment_id=result["amendment_id"],
        actor_id="buyer-hash",
        now_iso="2026-08-04T01:03:00+00:00",
    )
    assert applied["state_changed"] is True
    assert get_case_state(db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1")["quantity"] == 80


def test_destination_change_on_committed_case_requires_confirmation() -> None:
    db = _db()
    _seed(db)
    state = get_case_state(
        db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1"
    )
    state["case_status"] = "committed"
    db.execute(
        text("UPDATE conversation_case_state SET state_json=:state WHERE case_id='case-1'"),
        {"state": json.dumps(state)},
    )
    db.commit()

    result = record_case_turn(
        db,
        tenant_id="tenant-a",
        case_id="case-1",
        session_epoch="epoch-1",
        subject_ref="buyer-hash",
        source_message_id="message-committed-destination",
        message="Actually send them to Parramatta.",
    )

    assert result["status"] == "pending_confirmation"
    assert result["requires_confirmation"] is True
    assert get_case_state(
        db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1"
    )["destination"] == "Sydney"


def test_correction_supersedes_prior_value_without_deleting_history() -> None:
    db = _db()
    _seed(db)
    first = record_case_turn(
        db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1",
        subject_ref="buyer-hash", source_message_id="m1",
        message="Actually send them to Parramatta.",
    )
    second = record_case_turn(
        db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1",
        subject_ref="buyer-hash", source_message_id="m2",
        message="Correction: ship them to Penrith.",
    )

    assert first["status"] == second["status"] == "accepted"
    rows = db.execute(text(
        "SELECT id,status,supersedes_id FROM conversation_case_amendment "
        "WHERE field_name='destination' ORDER BY observed_at"
    )).fetchall()
    assert len(rows) == 2
    assert rows[0][1] == "superseded"
    assert rows[1][2] == rows[0][0]
    assert get_case_state(db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1")["destination"] == "Penrith"


def test_tenant_and_session_epoch_are_hard_isolation_boundaries() -> None:
    db = _db()
    _seed(db)
    _seed(db, tenant="tenant-b")
    _seed(db, epoch="epoch-2")
    record_case_turn(
        db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1",
        subject_ref="buyer-hash", source_message_id="m1", message="Ship them to Penrith.",
    )

    assert get_case_state(db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1")["destination"] == "Penrith"
    assert get_case_state(db, tenant_id="tenant-b", case_id="case-1", session_epoch="epoch-1")["destination"] == "Sydney"
    assert get_case_state(db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-2")["destination"] == "Sydney"


def test_ambiguous_reference_returns_typed_clarification() -> None:
    parsed = classify_case_turn("Make it double", current_state={"sku": "RGAM-0007"})
    assert parsed.dialogue_act == "clarify"
    assert parsed.reason == "quantity_anchor_required"
    assert parsed.proposed_value is None
