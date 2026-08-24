import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.conversation_case_state import ensure_case_state
from src.app.services.semantic_belief_state import (
    merge_semantic_belief,
    persist_semantic_belief,
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
    db.commit()
    return db


def _decision(*, confidence: float = 0.6, desired: str = "run an unfamiliar simulation") -> dict:
    return {
        "desired_outcome": desired,
        "interpretation_confidence": confidence,
        "catalog_authority": "blocked",
        "workload_hypotheses": [
            {
                "hypothesis_id": "local",
                "label": "Local execution",
                "confidence": confidence,
                "matched_claim_types": ["recommended_requirements"],
                "missing_claim_types": ["compatibility"],
                "evidence_coverage": "partial",
                "authority": "proposed",
            },
            {
                "hypothesis_id": "remote",
                "label": "Remote client",
                "confidence": 0.35,
                "matched_claim_types": [],
                "missing_claim_types": ["certification"],
                "evidence_coverage": "unresolved",
                "authority": "proposed",
            },
        ],
        "material_unknowns": [
            {
                "unknown_id": "execution-location",
                "description": "Where execution occurs",
                "resolution_source": "buyer",
                "material": True,
            }
        ],
    }


def test_belief_keeps_model_confidence_separate_from_evidence_support() -> None:
    belief = merge_semantic_belief(
        prior=None,
        semantic_decision=_decision(),
        accepted_evidence=[{
            "claim_type": "recommended_requirements",
            "claim_status": "verified",
            "citation_id": "official:req-1",
        }],
        compiled_requirements=[{
            "attribute_key": "ram_gb", "operator": ">=", "value": 32,
            "source_claim_ids": ["req-1"],
        }],
        trace_id="trace-1",
        observed_at="2026-08-07T01:00:00+00:00",
    )

    local = belief["hypotheses"][0]
    assert local["model_confidence"] == 0.6
    assert local["evidence_support"] == {"matched": 1, "required": 2, "ratio": 0.5}
    assert local["authorization"] == "proposed"
    assert belief["compiled_requirements"][0]["attribute_key"] == "ram_gb"
    assert belief["revision"] == 1


def test_paraphrase_updates_one_hypothesis_history_without_resetting_goal() -> None:
    first = merge_semantic_belief(
        prior=None,
        semantic_decision=_decision(),
        accepted_evidence=[],
        compiled_requirements=[],
        trace_id="trace-1",
        observed_at="2026-08-07T01:00:00+00:00",
    )
    second = merge_semantic_belief(
        prior=first,
        semantic_decision=_decision(confidence=0.72, desired="run an unfamiliar simulation"),
        accepted_evidence=[],
        compiled_requirements=[],
        trace_id="trace-2",
        observed_at="2026-08-07T01:01:00+00:00",
    )

    assert second["revision"] == 2
    assert second["goal"] == first["goal"]
    assert second["hypotheses"][0]["model_confidence"] == 0.72
    assert second["history"][-1]["trace_id"] == "trace-1"


def test_new_goal_supersedes_prior_generation_without_deleting_history() -> None:
    first = merge_semantic_belief(
        prior=None, semantic_decision=_decision(), accepted_evidence=[],
        compiled_requirements=[], trace_id="trace-1",
        observed_at="2026-08-07T01:00:00+00:00",
    )
    second = merge_semantic_belief(
        prior=first,
        semantic_decision=_decision(desired="edit professional video locally"),
        accepted_evidence=[], compiled_requirements=[], trace_id="trace-2",
        observed_at="2026-08-07T01:02:00+00:00",
    )

    assert second["generation"] == 2
    assert second["supersedes_revision"] == 1
    assert second["history"][-1]["goal"] == "run an unfamiliar simulation"


def test_persistence_is_tenant_and_epoch_scoped() -> None:
    db = _db()
    for tenant in ("tenant-a", "tenant-b"):
        ensure_case_state(
            db, tenant_id=tenant, case_id="semantic-1", session_epoch="epoch-1",
            subject_ref="buyer", authoritative_anchor={"quantity": 20},
            now_iso="2026-08-07T01:00:00+00:00",
        )

    result = persist_semantic_belief(
        db,
        tenant_id="tenant-a",
        case_id="semantic-1",
        session_epoch="epoch-1",
        semantic_decision=_decision(),
        accepted_evidence=[],
        compiled_requirements=[],
        trace_id="trace-1",
        observed_at="2026-08-07T01:01:00+00:00",
    )

    assert result["status"] == "persisted"
    rows = db.execute(text(
        "SELECT tenant_id,state_json FROM conversation_case_state ORDER BY tenant_id"
    )).fetchall()
    assert "semantic_belief" in json.loads(rows[0][1])
    assert "semantic_belief" not in json.loads(rows[1][1])


def test_same_trace_is_idempotent_and_does_not_create_another_revision() -> None:
    db = _db()
    ensure_case_state(
        db, tenant_id="tenant-a", case_id="semantic-1", session_epoch="epoch-1",
        subject_ref="buyer", authoritative_anchor={},
        now_iso="2026-08-07T01:00:00+00:00",
    )
    values = dict(
        tenant_id="tenant-a", case_id="semantic-1", session_epoch="epoch-1",
        semantic_decision=_decision(), accepted_evidence=[], compiled_requirements=[],
        trace_id="trace-1", observed_at="2026-08-07T01:01:00+00:00",
    )

    first = persist_semantic_belief(db, **values)
    second = persist_semantic_belief(db, **values)

    assert first["belief"]["revision"] == 1
    assert second["status"] == "already_persisted"
    assert second["belief"]["revision"] == 1


def test_semantic_belief_does_not_advance_canonical_case_revision() -> None:
    db = _db()
    created = ensure_case_state(
        db, tenant_id="tenant-a", case_id="semantic-1", session_epoch="epoch-1",
        subject_ref="buyer", authoritative_anchor={},
        now_iso="2026-08-07T01:00:00+00:00",
    )

    result = persist_semantic_belief(
        db,
        tenant_id="tenant-a", case_id="semantic-1", session_epoch="epoch-1",
        semantic_decision=_decision(), accepted_evidence=[], compiled_requirements=[],
        trace_id="trace-1", observed_at="2026-08-07T01:01:00+00:00",
    )

    row_version = db.execute(text(
        "SELECT version FROM conversation_case_state WHERE id=:id"
    ), {"id": created["case_state_id"]}).scalar_one()
    assert result["status"] == "persisted"
    assert row_version == created["version"]
