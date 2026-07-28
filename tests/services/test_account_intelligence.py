from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

from src.app.models.db import set_engine
from src.app.services.account_intelligence import (
    propose_party_link,
    propose_party_merge,
    rebuild_account_snapshot,
    record_account_activity,
    resolve_exact_external_identity,
)


def _migrate(engine) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260810_account_intelligence.py"
    spec = importlib.util.spec_from_file_location("account_intelligence_migration", path)
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


def test_exact_identity_is_tenant_scoped_and_snapshot_is_rebuildable(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'account.sqlite'}", future=True)
    _migrate(engine)
    set_engine(engine)
    first = resolve_exact_external_identity(
        tenant_id="tenant-a",
        source="csv",
        object_type="customer",
        external_id="shared-1",
        party_type="buyer_account",
        display_name="Acme",
    )
    replay = resolve_exact_external_identity(
        tenant_id="tenant-a",
        source="csv",
        object_type="customer",
        external_id="shared-1",
        party_type="buyer_account",
    )
    other = resolve_exact_external_identity(
        tenant_id="tenant-b",
        source="csv",
        object_type="customer",
        external_id="shared-1",
        party_type="buyer_account",
    )
    assert replay["party_id"] == first["party_id"]
    assert other["party_id"] != first["party_id"]

    record_account_activity(
        tenant_id="tenant-a",
        party_id=first["party_id"],
        activity_type="order",
        external_ref="order-1",
        occurred_at="2026-07-28T00:00:00Z",
        amount_cents=10_000,
        currency="AUD",
        payload={},
    )
    record_account_activity(
        tenant_id="tenant-a",
        party_id=first["party_id"],
        activity_type="return",
        external_ref="return-1",
        occurred_at="2026-07-28T01:00:00Z",
        payload={},
    )
    snapshot = rebuild_account_snapshot(
        tenant_id="tenant-a", party_id=first["party_id"]
    )
    assert snapshot["gross_value_cents"] == 10_000
    assert snapshot["return_rate"] == 1.0

    with pytest.raises(ValueError, match="party_not_in_tenant"):
        record_account_activity(
            tenant_id="tenant-b",
            party_id=first["party_id"],
            activity_type="order",
            external_ref="cross-tenant",
            occurred_at="2026-07-28T02:00:00Z",
            payload={},
        )

    link = propose_party_link(
        tenant_id="tenant-a",
        left_party_id=first["party_id"],
        right_party_id=resolve_exact_external_identity(
            tenant_id="tenant-a", source="csv", object_type="contact",
            external_id="contact-2", party_type="person",
        )["party_id"],
        relationship_type="contact_for",
        evidence={"source": "operator_review"},
        proposed_by="operator-1",
    )
    assert link["status"] == "proposed"
    assert link["execution_allowed"] is False

    merge = propose_party_merge(
        tenant_id="tenant-a",
        left_party_id=first["party_id"],
        right_party_id=resolve_exact_external_identity(
            tenant_id="tenant-a", source="csv", object_type="customer",
            external_id="possible-duplicate", party_type="buyer_account",
        )["party_id"],
        evidence={"shared_abn": "test-only"},
        proposed_by="operator-1",
    )
    assert merge["human_review_required"] is True
    assert merge["execution_allowed"] is False
