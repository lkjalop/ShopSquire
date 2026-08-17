from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.orm import Base
from src.app.services.decision_dependency_graph import (
    DecisionDependencyEdge,
    load_decision_dependency_edges,
    traverse_decision_dependencies,
)
from src.app.services.procurement_case_state import ProcurementCaseState
from src.app.services.procurement_decision_run import (
    StageReceipt,
    create_decision_run,
    create_decision_snapshot,
    persist_decision_run,
)


HASH_A = "a" * 64
HASH_B = "b" * 64


def _db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_persisted_artifact_edges_drive_selective_invalidation():
    db = _db()
    state = ProcurementCaseState(case_id="case-deps", revision=3, objective="fleet")
    snapshot = create_decision_snapshot(state, tenant_id="t1")
    run = create_decision_run(snapshot, idempotency_key="turn:1", status="completed", stage_receipts=(
        StageReceipt(
            stage="fit", stage_id="stage-fit", status="completed",
            started_at=snapshot.knowledge_cutoff, completed_at=snapshot.knowledge_cutoff,
            input_hash=HASH_A, output_hash=HASH_B,
            input_artifact_refs=("requirements:accepted", "catalog:exact"),
            output_artifact_refs=("fit:verdicts",), dependency_stage_ids=(),
        ),
        StageReceipt(
            stage="commercial", stage_id="stage-commercial", status="completed",
            started_at=snapshot.knowledge_cutoff, completed_at=snapshot.knowledge_cutoff,
            input_hash=HASH_B, output_hash=HASH_A,
            input_artifact_refs=("fit:verdicts", "inventory:current", "price:current"),
            output_artifact_refs=("commercial:shelves",),
            dependency_stage_ids=("stage-fit",),
        ),
        StageReceipt(
            stage="fulfilment", stage_id="stage-fulfilment", status="completed",
            started_at=snapshot.knowledge_cutoff, completed_at=snapshot.knowledge_cutoff,
            input_hash=HASH_A, output_hash=HASH_B,
            input_artifact_refs=("commercial:shelves", "supplier:offers"),
            output_artifact_refs=("fulfilment:options",),
            dependency_stage_ids=("stage-commercial",),
        ),
    ))
    persist_decision_run(db, run)

    edges = load_decision_dependency_edges(db, tenant_id="t1", case_id="case-deps")
    result = traverse_decision_dependencies(edges, changed_refs=("inventory:current",))
    assert result.affected_stage_ids == ("stage-commercial", "stage-fulfilment")
    assert result.affected_artifact_refs == (
        "commercial:shelves", "fulfilment:options",
    )
    assert "stage-fit" not in result.affected_stage_ids


def test_dependency_traversal_is_bounded():
    edges = [
        DecisionDependencyEdge(
            edge_id=f"e-{index}", run_id="run", tenant_id="t1", case_id="case",
            source_ref=f"artifact:{index}", target_ref=f"artifact:{index + 1}",
            relation="invalidates",
        )
        for index in range(10)
    ]
    result = traverse_decision_dependencies(
        edges, changed_refs=("artifact:0",), max_depth=2,
    )
    assert result.truncated is True
    assert result.visited_refs == ("artifact:0", "artifact:1", "artifact:2")
