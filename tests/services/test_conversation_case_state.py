import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.models.orm import ShoppingCase

from src.app.services.conversation_case_state import (
    CaseTurn,
    apply_case_amendment,
    classify_case_turn,
    decompose_case_obligations,
    ensure_case_state,
    get_case_state,
    record_case_turn,
    record_typed_case_patch_set,
    reduce_case_obligations,
)


class _FakeResult:
    def __init__(self, row=None, rowcount=0):
        self._row = row
        self.rowcount = rowcount

    def first(self):
        return self._row


class _CaptureCaseDb:
    def __init__(self) -> None:
        self.insert_params = None
        self.committed = False

    def execute(self, statement, params):
        sql = str(statement)
        if "FROM conversation_case_state" in sql:
            return _FakeResult(("state-1", json.dumps({"sku": "SKU-1"}), 1))
        if "field_name=:field" in sql:
            return _FakeResult(None)
        if "SELECT status FROM conversation_case_amendment" in sql:
            return _FakeResult(None)
        if "INSERT INTO conversation_case_amendment" in sql:
            self.insert_params = dict(params)
            return _FakeResult(rowcount=1)
        raise AssertionError(sql)

    def commit(self):
        self.committed = True


def test_case_amendment_binds_native_boolean_for_postgres(monkeypatch) -> None:
    from src.app.services import conversation_case_state as service

    db = _CaptureCaseDb()
    monkeypatch.setattr(
        service,
        "classify_case_turn",
        lambda _message, current_state: CaseTurn(
            "amend_destination", "destination", "Melbourne", 1.0,
            "high", True, "explicit_destination",
        ),
    )

    result = service.record_case_turn(
        db,
        tenant_id="tenant-a",
        case_id="case-1",
        session_epoch="epoch-1",
        subject_ref="buyer-hash",
        source_message_id="message-1",
        message="ship it to Melbourne",
    )

    assert result["status"] == "pending_confirmation"
    assert db.insert_params is not None
    assert db.insert_params["confirmation"] is True
    assert db.committed is True


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


def test_material_patch_advances_one_revision_across_case_projections() -> None:
    db = _db()
    ShoppingCase.__table__.create(db.bind)
    db.add(ShoppingCase(
        case_id="case-1", tenant_id="tenant-a", uid="buyer-1",
        status="active", retained_purpose="fleet", revision=1,
    ))
    db.commit()
    _seed(db)

    result = record_typed_case_patch_set(
        db, tenant_id="tenant-a", case_id="case-1", session_epoch="epoch-1",
        subject_ref="buyer-hash", source_message_id="message-quantity",
        expected_version=1,
        patches=[{"operation": "set", "path": "requested_quantity", "value": 30}],
    )

    assert result["version"] == 2
    assert db.query(ShoppingCase).filter_by(case_id="case-1").one().revision == 2
    row = db.execute(text(
        "SELECT version,state_json FROM conversation_case_state WHERE case_id='case-1'"
    )).one()
    assert row.version == 2
    state = json.loads(row.state_json)
    assert state["procurement_case_state"]["revision"] == 2
    assert state["procurement_case_state"]["requested_quantity"] == 30


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


def test_typed_multidestination_patch_persists_and_preserves_other_case_fields() -> None:
    db = _db()
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
            "objective": "Engineering simulation fleet",
            "semantic_resolution": {
                "hypotheses": [{"label": "Unreal Engine"}, {"label": "large CAD models"}],
            },
            "deadline": "2026-08-20T17:00:00+10:00",
            "budget": {"total_cents": 22_000_000, "currency": "AUD", "scope": "total"},
        },
        now_iso="2026-08-16T02:00:00+00:00",
    )
    result = record_typed_case_patch_set(
        db,
        tenant_id="tenant-a",
        case_id="case-60",
        session_epoch="epoch-1",
        subject_ref="buyer-hash",
        source_message_id="move-5",
        expected_version=1,
        patches=[{
            "operation": "move_quantity", "path": "destinations",
            "quantity": 5, "from_ref": "Perth", "to_ref": "Sydney",
        }],
        trace_id="trace-60",
        now_iso="2026-08-16T02:01:00+00:00",
    )

    updated = get_case_state(
        db, tenant_id="tenant-a", case_id="case-60", session_epoch="epoch-1"
    )["procurement_case_state"]
    assert result["version"] == 2
    assert updated["destinations"] == [
        {"location_ref": "Sydney", "quantity": 45, "location_kind": "unknown"},
        {"location_ref": "Perth", "quantity": 15, "location_kind": "unknown"},
    ]
    assert updated["workloads"] == ["Unreal Engine", "large CAD models"]
    assert updated["objective"] == "Engineering simulation fleet"
    assert result["commerce_authority"] is False


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


def test_relative_quantity_reduction_uses_the_sealed_case_quantity() -> None:
    by_amount = classify_case_turn(
        "Actually reduce it by 10 units.",
        current_state={"sku": "RGAM-0007", "quantity": 30},
    )
    to_amount = classify_case_turn(
        "Actually reduce it to 10 units.",
        current_state={"sku": "RGAM-0007", "quantity": 30},
    )

    assert by_amount.dialogue_act == "amend_quantity"
    assert by_amount.proposed_value == 20
    assert by_amount.reason == "relative_quantity_reduction"
    assert to_amount.dialogue_act == "amend_quantity"
    assert to_amount.proposed_value == 10
    assert to_amount.reason == "absolute_quantity"


def test_relative_quantity_without_a_selected_line_fails_closed() -> None:
    parsed = classify_case_turn(
        "Reduce it by 10.",
        current_state={"quantity": 30},
    )

    assert parsed.dialogue_act == "clarify"
    assert parsed.reason == "selected_product_anchor_required"
    assert parsed.proposed_value is None


def test_unresolved_semantic_case_can_amend_requested_demand_without_selecting_sku() -> None:
    obligations = reduce_case_obligations(
        "Actually reduce it by 10 units.",
        current_state={"quantity": 30},
        catalog_authority="blocked",
    )

    assert obligations[0]["kind"] == "quantity_amendment"
    assert obligations[0]["proposed_value"] == 20
    assert obligations[0]["status"] == "pending_confirmation"
    assert obligations[0]["authorization_granted"] is False


def test_mixed_turn_decomposes_every_obligation_without_executing_any() -> None:
    obligations = decompose_case_obligations(
        "Reduce it by 10, deliver it by Friday, then confirm the purchase order and pay a deposit.",
        current_state={"sku": "RGAM-0007", "quantity": 30},
    )

    assert [item["kind"] for item in obligations] == [
        "quantity_amendment",
        "deadline",
        "buyer_commitment",
        "payment_request",
    ]
    assert obligations[0]["proposed_value"] == 20
    assert all(item["authority"] == "proposed" for item in obligations)
    assert all(item["requires_reducer"] is True for item in obligations)


def test_mixed_turn_keeps_policy_support_and_supplier_status_as_read_only_obligations() -> None:
    message = (
        "Add 5 more, what is the return policy, can I file a warranty claim for this laptop, "
        "and has the supplier replied to the RFQ?"
    )
    proposed = decompose_case_obligations(
        message,
        current_state={"sku": "RGAM-0007", "quantity": 20},
    )
    kinds = {item["kind"] for item in proposed}
    assert {
        "policy_question", "support_question", "supplier_status",
    }.issubset(kinds)

    reduced = reduce_case_obligations(
        message,
        current_state={
            "sku": "RGAM-0007",
            "quantity": 20,
            "case_id": "FC-7",
            "rfq_ref": "RFQ-7",
        },
        catalog_authority="permitted",
    )
    by_kind = {item["kind"]: item for item in reduced}
    assert by_kind["policy_question"]["residual_route"] == "POLICY"
    assert by_kind["support_question"]["residual_route"] == "SUPPORT"
    assert by_kind["supplier_status"]["residual_route"] == "CONNECTOR"
    assert all(by_kind[kind]["authorization_granted"] is False for kind in (
        "policy_question", "support_question", "supplier_status",
    ))


def test_supplier_status_without_case_anchor_asks_for_reference() -> None:
    result = reduce_case_obligations(
        "Has the supplier replied to the RFQ?",
        current_state={},
        catalog_authority="permitted",
    )
    assert result[0]["kind"] == "supplier_status"
    assert result[0]["status"] == "clarify"
    assert result[0]["reason"] == "sourcing_case_anchor_required"


def test_place_noun_is_not_misread_as_order_commitment() -> None:
    assert decompose_case_obligations(
        "Find a pizza place near me.", current_state={}
    ) == ()


def test_mixed_reducer_blocks_commitment_behind_pending_quantity_amendment() -> None:
    result = reduce_case_obligations(
        "Reduce it by 10, deliver it by Friday, then confirm the purchase order.",
        current_state={
            "sku": "RGAM-0007",
            "quantity": 30,
            "budget": {"amount": 75000, "currency": "AUD", "scope": "total"},
            "destination": "Sydney",
            "atp_snapshot": {"source_version": "ATP-7", "observed_at": "2026-08-05T10:00:00Z"},
        },
        catalog_authority="permitted",
    )

    assert result[0]["status"] == "pending_confirmation"
    assert result[0]["proposed_value"] == 20
    assert result[-1]["kind"] == "buyer_commitment"
    assert result[-1]["status"] == "blocked"
    assert result[-1]["reason"] == "prior_obligation_requires_confirmation"


def test_commitment_requires_selected_sku_and_versioned_atp() -> None:
    missing_sku = reduce_case_obligations(
        "Confirm the purchase order.",
        current_state={"quantity": 20},
        catalog_authority="permitted",
    )
    missing_atp = reduce_case_obligations(
        "Confirm the purchase order.",
        current_state={"sku": "RGAM-0007", "quantity": 20},
        catalog_authority="permitted",
    )

    assert missing_sku[0]["reason"] == "selected_product_anchor_required"
    assert missing_atp[0]["reason"] == "versioned_atp_snapshot_required"


def test_commitment_is_routed_to_authorization_never_granted_by_case_reducer() -> None:
    result = reduce_case_obligations(
        "Confirm the purchase order.",
        current_state={
            "sku": "RGAM-0007",
            "quantity": 20,
            "atp_snapshot": {"source_version": "ATP-7", "observed_at": "2026-08-05T10:00:00Z"},
        },
        catalog_authority="permitted",
    )

    assert result[0]["status"] == "authorization_required"
    assert result[0]["residual_route"] == "AUTHORIZE"
    assert result[0]["authorization_granted"] is False


def test_accepted_amendment_invalidates_prior_version_and_projects_supersession() -> None:
    db = _db()
    db.execute(text("""
        CREATE TABLE temporal_dependency (
            id TEXT PRIMARY KEY, tenant_id TEXT, source_type TEXT, source_id TEXT,
            source_version TEXT, derived_type TEXT, derived_id TEXT, status TEXT,
            created_at TEXT, invalidated_at TEXT, invalidation_reason TEXT
        )
    """))
    db.execute(text("""
        CREATE TABLE decision_trace_events (
            id TEXT PRIMARY KEY, trace_id TEXT, event_type TEXT, source_type TEXT,
            source_id TEXT, target_type TEXT, target_id TEXT, payload TEXT,
            created_at TEXT, tenant_id TEXT
        )
    """))
    _seed(db)
    db.execute(text("""
        INSERT INTO temporal_dependency (
            id,tenant_id,source_type,source_id,source_version,derived_type,derived_id,status,created_at
        ) VALUES (
            'dep-1','tenant-a','conversation_case_state','case-1','1',
            'hippograph_edge','edge-old','active','2026-08-04T01:00:00+00:00'
        )
    """))
    db.commit()

    result = record_case_turn(
        db,
        tenant_id="tenant-a",
        case_id="case-1",
        session_epoch="epoch-1",
        subject_ref="buyer-hash",
        source_message_id="destination-with-trace",
        message="Ship them to Penrith.",
        trace_id="trace-1",
        now_iso="2026-08-04T01:05:00+00:00",
    )

    assert result["state_changed"] is True
    dependency = db.execute(text(
        "SELECT status,invalidation_reason FROM temporal_dependency WHERE id='dep-1'"
    )).first()
    assert dependency[0] == "invalidated"
    assert dependency[1].startswith("case_amended:")
    edge = db.execute(text(
        "SELECT event_type,source_id,target_id,payload FROM decision_trace_events"
    )).first()
    assert edge[0:3] == (
        "case_revision_superseded", "case-1@v1", "case-1@v2"
    )
    assert json.loads(edge[3])["authority"] == "evidence_only"
