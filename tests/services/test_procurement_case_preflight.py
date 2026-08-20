from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.conversation_case_state import ensure_case_state, get_case_state
from src.app.services.procurement_case_preflight import apply_case_patches_before_evaluation


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
            effective_at TEXT, created_at TEXT NOT NULL
        )
    """))
    db.commit()
    return db


def _seed(db: Session) -> dict:
    ensure_case_state(
        db,
        tenant_id="tenant-a",
        case_id="case-60",
        session_epoch="epoch-1",
        subject_ref="buyer-hash",
        authoritative_anchor={
            "quantity": 60,
            "destination_allocations": [
                {"location_ref": "Sydney", "quantity": 40},
                {"location_ref": "Perth", "quantity": 20},
            ],
            "objective": "Unreal Engine fleet",
            "semantic_resolution": {"hypotheses": [{"label": "Unreal Engine"}]},
        },
    )
    return get_case_state(
        db, tenant_id="tenant-a", case_id="case-60", session_epoch="epoch-1"
    )["procurement_case_state"]


def test_patch_is_applied_before_evaluation_and_retry_is_idempotent(monkeypatch) -> None:
    db = _db()
    state = _seed(db)
    monkeypatch.setattr("src.app.deps.hash_uid", lambda _uid: "buyer-hash")
    session = {
        "procurement_case_state": state,
        "case_patch_idempotency_key": "request-1",
    }
    patch = ({
        "operation": "move_quantity",
        "path": "destinations",
        "quantity": 5,
        "from_ref": "Perth",
        "to_ref": "Sydney",
    },)

    first = apply_case_patches_before_evaluation(
        db, tenant_id="tenant-a", uid="buyer", session_epoch="epoch-1",
        trace_id="trace-1", session=session, patches=patch,
    )
    retry = apply_case_patches_before_evaluation(
        db, tenant_id="tenant-a", uid="buyer", session_epoch="epoch-1",
        trace_id="trace-2", session={**session, "procurement_case_state": first.state.model_dump(mode="json")},
        patches=patch,
    )

    assert [(row.location_ref, row.quantity) for row in first.state.destinations] == [
        ("Sydney", 45), ("Perth", 15),
    ]
    assert retry.application["idempotent"] is True
    assert retry.state.revision == 2
    assert get_case_state(
        db, tenant_id="tenant-a", case_id="case-60", session_epoch="epoch-1"
    )["procurement_case_state"]["requested_quantity"] == 60


def test_competing_stale_revision_is_rejected(monkeypatch) -> None:
    db = _db()
    state = _seed(db)
    monkeypatch.setattr("src.app.deps.hash_uid", lambda _uid: "buyer-hash")
    common = {"procurement_case_state": state}
    patch = ({
        "operation": "move_quantity", "path": "destinations", "quantity": 5,
        "from_ref": "Perth", "to_ref": "Sydney",
    },)
    apply_case_patches_before_evaluation(
        db, tenant_id="tenant-a", uid="buyer", session_epoch="epoch-1",
        trace_id="trace-a", session={**common, "case_patch_idempotency_key": "request-a"}, patches=patch,
    )

    try:
        apply_case_patches_before_evaluation(
            db, tenant_id="tenant-a", uid="buyer", session_epoch="epoch-1",
            trace_id="trace-b", session={**common, "case_patch_idempotency_key": "request-b"}, patches=patch,
        )
    except ValueError as exc:
        assert str(exc) == "case_revision_conflict"
    else:
        raise AssertionError("stale competing patch was accepted")


def test_temporal_patch_persists_resolution_in_same_case_revision(monkeypatch) -> None:
    db = _db()
    state = _seed(db)
    monkeypatch.setattr("src.app.deps.hash_uid", lambda _uid: "buyer-hash")

    result = apply_case_patches_before_evaluation(
        db,
        tenant_id="tenant-a",
        uid="buyer",
        session_epoch="epoch-1",
        trace_id="trace-temporal",
        session={
            "procurement_case_state": state,
            "case_patch_idempotency_key": "request-temporal",
        },
        patches=({
            "operation": "set",
            "path": "temporal.original_expression",
            "value": "within four days",
        },),
    )

    assert result.state.revision == 2
    assert result.state.temporal is not None
    assert result.state.temporal.resolution_status == "resolved"
    assert result.state.temporal.required_by is not None
    assert result.state.temporal.interpretation_instant is not None
    assert result.state.temporal.calendar_version is not None
    assert result.application["commerce_authority"] is False
