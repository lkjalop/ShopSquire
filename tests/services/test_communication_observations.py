from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

from src.app.models.db import set_engine
from src.app.services.communication_observations import record_message_observation


def _migrate(engine) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260812_communication_observations.py"
    spec = importlib.util.spec_from_file_location("communication_observation_migration", path)
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


def test_supplier_and_buyer_messages_are_observations_not_authority(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'messages.sqlite'}", future=True)
    _migrate(engine)
    set_engine(engine)
    supplier = record_message_observation(
        tenant_id="tenant-a",
        party_type="supplier",
        direction="inbound",
        channel="synthetic",
        provider_message_id="shared-message",
        purpose="rfq_reply",
        consent_status="not_required",
        security_status="quarantined",
        sanitized_payload={"body": "quoted price"},
        case_ref="case-a",
    )
    buyer = record_message_observation(
        tenant_id="tenant-b",
        party_type="buyer",
        direction="inbound",
        channel="synthetic",
        provider_message_id="shared-message",
        purpose="order_clarification",
        consent_status="granted",
        security_status="accepted",
        sanitized_payload={"body": "please pay this invoice"},
        case_ref="case-b",
    )
    replay = record_message_observation(
        tenant_id="tenant-a",
        party_type="supplier",
        direction="inbound",
        channel="synthetic",
        provider_message_id="shared-message",
        purpose="rfq_reply",
        consent_status="not_required",
        security_status="quarantined",
        sanitized_payload={"body": "changed replay"},
    )
    assert supplier["authority"] == "observation_only"
    assert buyer["authority"] == "observation_only"
    assert buyer["id"] != supplier["id"]
    assert replay["duplicate"] is True
    assert replay["id"] == supplier["id"]
