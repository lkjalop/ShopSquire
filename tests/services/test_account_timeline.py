from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

from src.app.models.db import set_engine
from src.app.services.account_intelligence import (
    get_account_timeline,
    list_identity_resolution_proposals,
    list_parties,
    propose_party_merge,
    propose_party_split,
    record_account_activity,
    resolve_exact_external_identity,
    resolve_identity_resolution_proposal,
)
from src.app.services.conversation_fact_observations import (
    record_conversation_fact_observations,
)


def _apply(engine, filename: str) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        original = module.op
        module.op = operations
        try:
            module.upgrade()
        finally:
            module.op = original


def _setup(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'timeline.sqlite'}", future=True)
    for migration in (
        "20260810_account_intelligence.py",
        "20260814_conversation_fact_observations.py",
        "20260819_party_timeline.py",
    ):
        _apply(engine, migration)
    set_engine(engine)
    return engine


def test_timeline_preserves_authority_provenance_and_tenant_scope(tmp_path):
    _setup(tmp_path)
    account = resolve_exact_external_identity(
        tenant_id="tenant-a",
        source="csv",
        object_type="customer",
        external_id="buyer-hash-1",
        party_type="buyer_account",
        display_name="Acme Buyer",
    )
    record_account_activity(
        tenant_id="tenant-a",
        party_id=account["party_id"],
        activity_type="order",
        external_ref="order-1",
        occurred_at="2026-07-28T00:00:00Z",
        amount_cents=12_000,
        currency="AUD",
        payload={"status": "paid"},
    )
    record_conversation_fact_observations(
        tenant_id="tenant-a",
        subject_ref="buyer-hash-1",
        source_message_id="message-1",
        trace_id="trace-1",
        message="We need 20 units monthly with a budget of AUD 5000.",
    )

    listed = list_parties(tenant_id="tenant-a", query="buyer-hash")
    assert [item["party_id"] for item in listed] == [account["party_id"]]
    timeline = get_account_timeline(
        tenant_id="tenant-a", party_id=account["party_id"]
    )
    assert timeline["party"]["authority"] == "authoritative_party_record"
    assert any(
        event["event_class"] == "operational_activity"
        and event["authority"] == "operational_record"
        for event in timeline["timeline"]
    )
    conversation = next(
        event
        for event in timeline["timeline"]
        if event["event_class"] == "conversation_observation"
    )
    assert conversation["authority"] == "observation_only"
    assert conversation["provenance"]["source_message_id"] == "message-1"
    assert conversation["provenance"]["trace_id"] == "trace-1"
    assert timeline["authority_policy"]["conversation_facts"] == "observation_only"

    assert list_parties(tenant_id="tenant-b", query="buyer-hash") == []
    with pytest.raises(ValueError, match="party_not_in_tenant"):
        get_account_timeline(
            tenant_id="tenant-b", party_id=account["party_id"]
        )


def test_merge_and_split_approval_never_executes_identity_change(tmp_path):
    _setup(tmp_path)
    left = resolve_exact_external_identity(
        tenant_id="tenant-a", source="csv", object_type="customer",
        external_id="left", party_type="buyer_account",
    )["party_id"]
    right = resolve_exact_external_identity(
        tenant_id="tenant-a", source="csv", object_type="customer",
        external_id="right", party_type="buyer_account",
    )["party_id"]

    merge = propose_party_merge(
        tenant_id="tenant-a",
        left_party_id=left,
        right_party_id=right,
        evidence={"shared_business_id": "review-only"},
        proposed_by="operator-1",
    )
    split = propose_party_split(
        tenant_id="tenant-a",
        left_party_id=left,
        right_party_id=right,
        evidence={"incorrect_link": "review-only"},
        proposed_by="operator-2",
    )
    assert merge["id"] != split["id"]
    assert merge["execution_allowed"] is False
    assert split["execution_allowed"] is False

    resolved = resolve_identity_resolution_proposal(
        tenant_id="tenant-a",
        proposal_id=merge["id"],
        resolution="approved",
        resolved_by="owner-1",
        note="Evidence reviewed; execute only in a separate controlled workflow.",
    )
    assert resolved["status"] == "approved"
    assert resolved["execution_allowed"] is False
    assert resolved["manual_execution_required"] is True

    proposals = list_identity_resolution_proposals(tenant_id="tenant-a")
    approved = next(item for item in proposals if item["id"] == merge["id"])
    assert approved["proposed_by"] == "operator-1"
    assert approved["resolved_by"] == "owner-1"
    assert approved["resolution_note"].startswith("Evidence reviewed")
    assert next(item for item in proposals if item["id"] == split["id"])["status"] == "proposed"

    with pytest.raises(ValueError, match="already_resolved"):
        resolve_identity_resolution_proposal(
            tenant_id="tenant-a",
            proposal_id=merge["id"],
            resolution="rejected",
            resolved_by="owner-2",
            note="Cannot overwrite the recorded disposition.",
        )
    with pytest.raises(ValueError, match="not_in_tenant"):
        resolve_identity_resolution_proposal(
            tenant_id="tenant-b",
            proposal_id=split["id"],
            resolution="approved",
            resolved_by="owner-2",
            note="Cross-tenant attempt.",
        )
