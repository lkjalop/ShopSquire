from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from src.app.models.db import set_engine
from src.app.services.account_intelligence import (
    execute_identity_resolution_proposal,
    preview_identity_resolution_execution,
    propose_party_merge,
    propose_party_split,
    record_account_activity,
    resolve_canonical_party,
    resolve_exact_external_identity,
    resolve_identity_resolution_proposal,
)


def _migrate(engine) -> None:
    root = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    for filename in (
        "20260810_account_intelligence.py",
        "20260819_party_timeline.py",
        "20260822_party_redirect_execution.py",
    ):
        spec = importlib.util.spec_from_file_location(filename, root / filename)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with engine.begin() as connection:
            original = module.op
            module.op = Operations(MigrationContext.configure(connection))
            try:
                module.upgrade()
            finally:
                module.op = original


def _party(tenant: str, external_id: str) -> str:
    return resolve_exact_external_identity(
        tenant_id=tenant,
        source="test",
        object_type="account",
        external_id=external_id,
        party_type="buyer_account",
        display_name=external_id,
    )["party_id"]


def _approve(tenant: str, proposal_id: str) -> None:
    resolve_identity_resolution_proposal(
        tenant_id=tenant,
        proposal_id=proposal_id,
        resolution="approved",
        resolved_by="reviewer",
        note="Evidence independently reviewed.",
    )


def test_merge_preview_execution_is_append_only_idempotent_and_versioned(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'redirect.sqlite'}",
        future=True,
    )
    _migrate(engine)
    set_engine(engine)
    tenant = "tenant-a"
    left, right = _party(tenant, "left"), _party(tenant, "right")
    record_account_activity(
        tenant_id=tenant,
        party_id=left,
        activity_type="order",
        external_ref="order-1",
        occurred_at="2026-01-01T00:00:00Z",
        payload={},
    )
    proposal = propose_party_merge(
        tenant_id=tenant,
        left_party_id=left,
        right_party_id=right,
        evidence={"same_registration": True},
        proposed_by="proposer",
    )
    assert proposal["decision_type"] == "merge_proposal"
    with engine.connect() as connection:
        stored_kind = connection.execute(
            text(
                "SELECT decision_type FROM identity_resolution_decision WHERE id=:id"
            ),
            {"id": proposal["id"]},
        ).scalar_one()
    assert stored_kind == "merge_proposal"
    _approve(tenant, proposal["id"])

    preview = preview_identity_resolution_execution(
        tenant_id=tenant, proposal_id=proposal["id"]
    )
    assert preview["graph_version"] == 0
    assert preview["impact_counts"]["account_activities"] == 1
    assert preview["execution_policy"]["moves_historical_records"] is False
    assert preview["executable"] is True

    executed = execute_identity_resolution_proposal(
        tenant_id=tenant,
        proposal_id=proposal["id"],
        executed_by="executor",
        expected_version=0,
        idempotency_key="merge-left-right-v1",
        note="Approved redirect execution.",
    )
    replay = execute_identity_resolution_proposal(
        tenant_id=tenant,
        proposal_id=proposal["id"],
        executed_by="executor",
        expected_version=0,
        idempotency_key="merge-left-right-v1",
        note="Approved redirect execution.",
    )
    assert executed["graph_version"] == 1
    assert replay["event_id"] == executed["event_id"]
    assert replay["idempotent_replay"] is True
    assert resolve_canonical_party(
        tenant_id=tenant, party_id=left
    )["canonical_party_id"] == right
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT party_id FROM account_activity WHERE external_ref='order-1'")
        ).scalar_one() == left
        assert connection.execute(
            text("SELECT COUNT(*) FROM party_redirect_event")
        ).scalar_one() == 1
        with pytest.raises(Exception, match="append_only"):
            connection.execute(
                text("DELETE FROM party_redirect_event WHERE id=:id"),
                {"id": executed["event_id"]},
            )


def test_execution_requires_four_eyes_and_current_graph_version(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'guards.sqlite'}",
        future=True,
    )
    _migrate(engine)
    set_engine(engine)
    left, right = _party("tenant-a", "left"), _party("tenant-a", "right")
    proposal = propose_party_merge(
        tenant_id="tenant-a",
        left_party_id=left,
        right_party_id=right,
        evidence={},
        proposed_by="same-operator",
    )
    _approve("tenant-a", proposal["id"])
    with pytest.raises(ValueError, match="four_eyes"):
        execute_identity_resolution_proposal(
            tenant_id="tenant-a", proposal_id=proposal["id"],
            executed_by="same-operator", expected_version=0,
            idempotency_key="four-eyes-check", note="Must fail.",
        )
    with pytest.raises(ValueError, match="graph_version_conflict"):
        execute_identity_resolution_proposal(
            tenant_id="tenant-a", proposal_id=proposal["id"],
            executed_by="executor", expected_version=7,
            idempotency_key="stale-version-check", note="Must fail.",
        )


def test_split_appends_reversal_and_restores_original_canonical_party(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'split.sqlite'}",
        future=True,
    )
    _migrate(engine)
    set_engine(engine)
    tenant = "tenant-a"
    left, right = _party(tenant, "left"), _party(tenant, "right")
    merge = propose_party_merge(
        tenant_id=tenant, left_party_id=left, right_party_id=right,
        evidence={}, proposed_by="merge-proposer",
    )
    _approve(tenant, merge["id"])
    merge_event = execute_identity_resolution_proposal(
        tenant_id=tenant, proposal_id=merge["id"], executed_by="merge-executor",
        expected_version=0, idempotency_key="merge-before-split",
        note="Merge redirect.",
    )
    split = propose_party_split(
        tenant_id=tenant, left_party_id=left, right_party_id=right,
        evidence={"identity_documents_differ": True}, proposed_by="split-proposer",
    )
    _approve(tenant, split["id"])
    preview = preview_identity_resolution_execution(
        tenant_id=tenant, proposal_id=split["id"]
    )
    assert preview["executable"] is True
    reversed_event = execute_identity_resolution_proposal(
        tenant_id=tenant, proposal_id=split["id"], executed_by="split-executor",
        expected_version=1, idempotency_key="split-reversal-v1",
        note="Reverse incorrect merge.",
    )

    assert reversed_event["event_type"] == "split_reversal"
    assert reversed_event["supersedes_event_id"] == merge_event["event_id"]
    assert resolve_canonical_party(
        tenant_id=tenant, party_id=left
    )["canonical_party_id"] == left
    with engine.connect() as connection:
        events = connection.execute(
            text(
                "SELECT event_type FROM party_redirect_event ORDER BY graph_version"
            )
        ).fetchall()
    assert [str(row[0]) for row in events] == [
        "merge_redirect", "split_reversal",
    ]
