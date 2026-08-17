from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.orm import Base
from src.app.services.procurement_case_state import ProcurementCaseState
from src.app.services.procurement_decision_run import (
    EvidenceWatermark,
    StageReceipt,
    create_decision_run,
    create_decision_snapshot,
    load_decision_runs,
    persist_decision_run,
)


def _state(revision: int = 3) -> ProcurementCaseState:
    return ProcurementCaseState(
        case_id="case-1", revision=revision, objective="60 workstations",
        workloads=["real-time 3D"], requested_quantity=60,
    )


def _db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_snapshot_is_stable_and_keeps_knowledge_separate_from_effective_time():
    known = datetime(2026, 8, 16, tzinfo=timezone.utc)
    effective = known + timedelta(days=4)
    watermark = EvidenceWatermark(
        source="inventory:network", observed_at=known.isoformat(), state="current",
    )

    first = create_decision_snapshot(
        _state(), tenant_id="portfolio", knowledge_cutoff=known,
        evaluation_time=effective, evidence_watermarks=(watermark,),
    )
    second = create_decision_snapshot(
        _state(), tenant_id="portfolio", knowledge_cutoff=known,
        evaluation_time=effective, evidence_watermarks=(watermark,),
    )

    assert first == second
    assert first.state_hash == second.state_hash
    assert first.knowledge_cutoff != first.evaluation_time


def test_completed_stage_requires_an_output_hash():
    now = datetime.now(timezone.utc).isoformat()
    with pytest.raises(ValueError, match="completed_stage_requires_output_hash"):
        StageReceipt(
            stage="fit", status="completed", started_at=now, completed_at=now,
            input_hash="a" * 64,
        )


def test_stage_receipt_preserves_inventory_tool_selection_receipt():
    now = datetime.now(timezone.utc).isoformat()
    receipt = StageReceipt(
        stage="inventory_source", stage_id="stage-inventory", status="completed",
        started_at=now, completed_at=now, input_hash="a" * 64, output_hash="b" * 64,
        tool_selection_receipts=({
            "capability": "inventory_availability", "outcome": "selected",
            "selected_deployment_ids": ["catalog"],
        },),
    )
    assert receipt.tool_selection_receipts[0]["outcome"] == "selected"


def test_decision_run_is_append_only_and_idempotent():
    db = _db()
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    snapshot = create_decision_snapshot(
        _state(), tenant_id="portfolio", knowledge_cutoff=now, evaluation_time=now,
    )
    run = create_decision_run(
        snapshot, idempotency_key="buyer-turn-1", status="degraded", now=now,
    )

    assert persist_decision_run(db, run) == run
    assert persist_decision_run(db, run) == run
    assert load_decision_runs(db, tenant_id="portfolio", case_id="case-1") == [run]
    assert load_decision_runs(db, tenant_id="other", case_id="case-1") == []


def test_same_idempotency_key_cannot_hide_a_different_run():
    db = _db()
    now = datetime(2026, 8, 16, tzinfo=timezone.utc)
    first = create_decision_run(
        create_decision_snapshot(_state(), tenant_id="portfolio", knowledge_cutoff=now),
        idempotency_key="turn-1", status="completed", now=now,
    )
    persist_decision_run(db, first)
    changed_state = _state().model_copy(update={"objective": "different objective"})
    changed = create_decision_run(
        create_decision_snapshot(changed_state, tenant_id="portfolio", knowledge_cutoff=now),
        idempotency_key="turn-1", status="failed", now=now,
    )

    with pytest.raises(ValueError, match="decision_run_idempotency_conflict"):
        persist_decision_run(db, changed)
