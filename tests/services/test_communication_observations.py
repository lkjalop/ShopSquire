from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.models.db import set_engine
from src.app.services.communication_party_binding import bind_authoritative_party
from src.app.services.communication_observations import record_message_observation


def _migrate(engine) -> None:
    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        for filename in (
            "20260810_account_intelligence.py",
            "20260812_communication_observations.py",
            "20260826_communication_lifecycle.py",
            "20260827_party_identity_authority.py",
        ):
            path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / filename
            spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            module.op = operations
            module.upgrade()


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


def test_message_party_ref_must_be_authoritative_and_in_tenant(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'binding.sqlite'}", future=True)
    _migrate(engine)
    session_factory = sessionmaker(bind=engine, future=True)
    with session_factory() as db:
        binding = bind_authoritative_party(
            db,
            tenant_id="tenant-a",
            party_type="supplier",
            source="supplier_registry",
            object_type="approved_supplier",
            external_id="supplier-17",
            authority="approved_supplier_registry",
            provenance_ref="registry:supplier-17:v3",
        )
        accepted = record_message_observation(
            db=db,
            tenant_id="tenant-a",
            party_type="supplier",
            direction="outbound",
            channel="synthetic",
            provider_message_id="message-a",
            purpose="rfq",
            consent_status="not_required",
            security_status="accepted",
            sanitized_payload={"body": "Please quote"},
            party_ref=binding["party_id"],
        )
        assert accepted["duplicate"] is False

        import pytest

        with pytest.raises(ValueError, match="authoritative_party_binding_required"):
            record_message_observation(
                db=db,
                tenant_id="tenant-b",
                party_type="supplier",
                direction="outbound",
                channel="synthetic",
                provider_message_id="message-b",
                purpose="rfq",
                consent_status="not_required",
                security_status="accepted",
                sanitized_payload={"body": "Cross-tenant attempt"},
                party_ref=binding["party_id"],
            )
