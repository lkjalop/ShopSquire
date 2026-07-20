from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.market_facts import record_atp_fact, record_marketing_event


MIGRATION = (Path(__file__).resolve().parents[2] / "alembic" / "versions" /
             "20260721_market_fact_contract.py")


@pytest.fixture()
def db():
    spec = importlib.util.spec_from_file_location("market_fact_contract", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        migration.upgrade()
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_atp_facts_are_tenant_scoped_and_deduplicated(db):
    fact = {
        "tenant_id": "tenant-a", "deduplication_id": "erp:42", "source_system": "erp",
        "source_record_id": "42", "sku": "SKU-1", "location_id": "SYD",
        "requested_quantity": 20, "on_hand_quantity": 12, "committed_quantity": 4,
        "incoming_receipts_quantity": 10, "confirmed_quantity": 18,
        "observed_at": "2026-07-20T00:00:00Z", "confidence": 1.7,
        "provenance_chain": ["erp/order/42"],
    }
    assert record_atp_fact(db, fact) is True
    assert record_atp_fact(db, fact) is False
    assert record_atp_fact(db, fact | {"tenant_id": "tenant-b"}) is True
    rows = db.execute(text(
        "SELECT tenant_id, confidence, provenance_json FROM inventory_atp_fact ORDER BY tenant_id"
    )).fetchall()
    assert rows == [("tenant-a", 1.0, '["erp/order/42"]'),
                    ("tenant-b", 1.0, '["erp/order/42"]')]


def test_marketing_facts_keep_consent_and_campaign_separate_from_inventory(db):
    fact = {
        "tenant_id": "tenant-a", "deduplication_id": "ga4:event-1",
        "source_system": "ga4", "event_type": "add_to_cart",
        "occurred_at": "2026-07-20T01:00:00Z", "sku": "SKU-1",
        "campaign_id": "campaign-7", "consent_state": "granted",
    }
    assert record_marketing_event(db, fact) is True
    row = db.execute(text(
        "SELECT event_type, campaign_id, consent_state FROM marketing_event_fact"
    )).one()
    assert row == ("add_to_cart", "campaign-7", "granted")
    with pytest.raises(ValueError, match="tenant_id"):
        record_marketing_event(db, fact | {"tenant_id": ""})
