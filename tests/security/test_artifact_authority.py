from __future__ import annotations

import hashlib
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.security.artifact_authority import (
    bind_decision,
    evaluate_bound_artifacts,
    invalidate_bindings_for_late_verdict,
    record_verdict,
)
from src.app.policy.execution_gate import decide
from src.app.policy.action_authority_matrix import AuthDecision


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.exec_driver_sql("""
        CREATE TABLE artifact_security_verdicts (
          id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, tenant_id TEXT NOT NULL,
          case_id TEXT, artifact_sha256 TEXT NOT NULL, source_type TEXT NOT NULL,
          verdict_version INTEGER NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL,
          coverage_json TEXT NOT NULL, supersedes_verdict_id TEXT, created_at TEXT NOT NULL,
          UNIQUE(tenant_id, artifact_id, verdict_version))""")
        conn.exec_driver_sql("""
        CREATE TABLE artifact_decision_bindings (
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
          artifact_sha256 TEXT NOT NULL, verdict_id TEXT NOT NULL, verdict_version INTEGER NOT NULL,
          decision_kind TEXT NOT NULL, decision_id TEXT NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL, invalidated_at TEXT, invalidation_reason TEXT,
          UNIQUE(tenant_id, artifact_id, decision_kind, decision_id))""")
        conn.exec_driver_sql("""
        CREATE TABLE artifact_security_incidents (
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, artifact_id TEXT NOT NULL,
          binding_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL)""")
    with Session(engine) as session:
        yield session


def _advance(db, *, tenant="t1", artifact="a1", target="clean"):
    sha = hashlib.sha256(b"artifact").hexdigest()
    states = ["received", "admitted", "pending", target]
    rows = []
    for idx, state in enumerate(states):
        rows.append(record_verdict(
            db, artifact_id=artifact, tenant_id=tenant, artifact_sha256=sha,
            state=state, reason=state, expected_previous_version=idx,
        ))
    return rows


def test_only_exact_current_clean_verdict_can_authorize(db):
    rows = _advance(db)
    assert rows[-1]["verdict_version"] == 4
    assert evaluate_bound_artifacts(db, tenant_id="t1", artifact_ids=["a1"]).allowed is True
    assert evaluate_bound_artifacts(db, tenant_id="other", artifact_ids=["a1"]).allowed is False


@pytest.mark.parametrize("state", ["pending", "degraded", "quarantined"])
def test_non_clean_artifact_never_authorizes(db, state):
    sha = hashlib.sha256(state.encode()).hexdigest()
    record_verdict(db, artifact_id=state, tenant_id="t1", artifact_sha256=sha, state="received", reason="received")
    if state == "pending":
        record_verdict(db, artifact_id=state, tenant_id="t1", artifact_sha256=sha, state="admitted", reason="admitted")
        record_verdict(db, artifact_id=state, tenant_id="t1", artifact_sha256=sha, state="pending", reason="pending")
    else:
        record_verdict(db, artifact_id=state, tenant_id="t1", artifact_sha256=sha, state=state, reason=state)
    result = evaluate_bound_artifacts(db, tenant_id="t1", artifact_ids=[state])
    assert result.allowed is False
    assert state in " ".join(result.blocked_states)


def test_late_verdict_invalidates_unexecuted_and_opens_incident_for_executed(db):
    _advance(db)
    queued = bind_decision(db, tenant_id="t1", artifact_id="a1", decision_kind="rfq", decision_id="rfq-1")
    executed = bind_decision(db, tenant_id="t1", artifact_id="a1", decision_kind="message", decision_id="msg-1")
    db.execute(text("UPDATE artifact_decision_bindings SET status='queued' WHERE id=:id"), {"id": queued["id"]})
    db.execute(text("UPDATE artifact_decision_bindings SET status='executed' WHERE id=:id"), {"id": executed["id"]})
    record_verdict(
        db, artifact_id="a1", tenant_id="t1", artifact_sha256=hashlib.sha256(b"artifact").hexdigest(),
        state="quarantined", reason="late_prompt_injection", expected_previous_version=4,
    )
    result = invalidate_bindings_for_late_verdict(db, tenant_id="t1", artifact_id="a1", reason="late_prompt_injection")
    assert result["invalidated_binding_ids"] == [queued["id"]]
    assert len(result["incident_ids"]) == 1


def test_illegal_state_transition_is_rejected(db):
    record_verdict(db, artifact_id="a1", tenant_id="t1", artifact_sha256="0" * 64, state="received", reason="received")
    with pytest.raises(ValueError, match="illegal_artifact_transition"):
        record_verdict(db, artifact_id="a1", tenant_id="t1", artifact_sha256="0" * 64, state="clean", reason="skip")


def test_execution_gate_blocks_pending_bound_artifact_server_side(db, monkeypatch):
    sha = hashlib.sha256(b"pending").hexdigest()
    record_verdict(db, artifact_id="pending", tenant_id="t1", artifact_sha256=sha, state="received", reason="received")
    record_verdict(db, artifact_id="pending", tenant_id="t1", artifact_sha256=sha, state="admitted", reason="admitted")
    record_verdict(db, artifact_id="pending", tenant_id="t1", artifact_sha256=sha, state="pending", reason="pending")

    @contextmanager
    def _session():
        yield db

    monkeypatch.setattr("src.app.models.db.db_session", _session)
    verdict = decide(
        "purchase_order",
        tenant_id="t1",
        context={"artifact_ids": ["pending"], "artifact_required": True},
    )
    assert verdict.decision is AuthDecision.BLOCK
    assert verdict.rule_id == "ARTIFACT-01"


def test_fast_and_deep_lanes_append_one_versioned_artifact_history(db, monkeypatch):
    from src.app.routers import vision

    @contextmanager
    def _session():
        yield db

    monkeypatch.setattr(vision, "db_session", _session)
    sha = hashlib.sha256(b"same-upload").hexdigest()
    pending = vision._persist_artifact_verdict(
        artifact_id="upload-123", sha256=sha, state="pending",
        coverage={"strict_admission": "pass", "provider": "skipped"},
    )
    clean = vision._persist_artifact_verdict(
        artifact_id="upload-123", sha256=sha, state="clean",
        coverage={"strict_admission": "pass", "provider": "pass"},
    )
    assert (pending["verdict_version"], pending["state"]) == (3, "pending")
    assert (clean["verdict_version"], clean["state"]) == (4, "clean")
