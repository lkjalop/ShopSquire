from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.market_facts import (
    MarketFactRejected, record_atp_fact, record_marketing_event, sign_fact,
)


MIGRATION = (Path(__file__).resolve().parents[2] / "alembic" / "versions" /
             "20260721_market_fact_contract.py")
GOVERNANCE_MIGRATION = (Path(__file__).resolve().parents[2] / "alembic" / "versions" /
                        "20260722_market_fact_governance.py")
QUARANTINE_DEDUP_MIGRATION = (Path(__file__).resolve().parents[2] / "alembic" / "versions" /
                              "20260723_market_fact_quarantine_dedup.py")


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
        spec2 = importlib.util.spec_from_file_location("market_fact_governance", GOVERNANCE_MIGRATION)
        governance = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(governance)
        governance.op = Operations(MigrationContext.configure(connection))
        governance.upgrade()
        spec3 = importlib.util.spec_from_file_location(
            "market_fact_quarantine_dedup", QUARANTINE_DEDUP_MIGRATION)
        quarantine_dedup = importlib.util.module_from_spec(spec3)
        spec3.loader.exec_module(quarantine_dedup)
        quarantine_dedup.op = Operations(MigrationContext.configure(connection))
        quarantine_dedup.upgrade()
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_atp_facts_are_tenant_scoped_and_deduplicated(db, monkeypatch):
    monkeypatch.setenv("MARKET_SOURCE_ERP_SECRET", "erp-test-secret")
    fact = {
        "tenant_id": "tenant-a", "deduplication_id": "erp:42", "source_system": "erp",
        "source_record_id": "42", "sku": "SKU-1", "location_id": "SYD",
        "requested_quantity": 20, "on_hand_quantity": 12, "committed_quantity": 4,
        "incoming_receipts_quantity": 10, "confirmed_quantity": 18,
        "observed_at": "2026-07-20T00:00:00Z", "confidence": 1.7,
        "provenance_chain": ["erp/order/42"],
    }
    fact["signature"] = sign_fact(fact, "erp-test-secret")
    evaluation_time = datetime(2026, 7, 21, tzinfo=timezone.utc)
    assert record_atp_fact(db, fact, now=evaluation_time) is True
    assert record_atp_fact(db, fact, now=evaluation_time) is False
    tenant_b = fact | {"tenant_id": "tenant-b"}
    tenant_b["signature"] = sign_fact(tenant_b, "erp-test-secret")
    assert record_atp_fact(db, tenant_b, now=evaluation_time) is True
    rows = db.execute(text(
        "SELECT tenant_id, confidence, provenance_json FROM inventory_atp_fact ORDER BY tenant_id"
    )).fetchall()
    assert rows == [("tenant-a", 1.0, '["erp/order/42"]'),
                    ("tenant-b", 1.0, '["erp/order/42"]')]


def test_marketing_facts_keep_consent_and_campaign_separate_from_inventory(db, monkeypatch):
    monkeypatch.setenv("MARKET_SOURCE_GA4_SECRET", "ga4-test-secret")
    fact = {
        "tenant_id": "tenant-a", "deduplication_id": "ga4:event-1",
        "source_system": "ga4", "event_type": "add_to_cart",
        "occurred_at": "2026-07-20T01:00:00Z", "sku": "SKU-1",
        "campaign_id": "campaign-7", "consent_state": "granted",
        "source_record_id": "event-1", "provenance_chain": ["ga4/event-1"],
    }
    fact["signature"] = sign_fact(fact, "ga4-test-secret")
    assert record_marketing_event(db, fact) is True
    row = db.execute(text(
        "SELECT event_type, campaign_id, consent_state FROM marketing_event_fact"
    )).one()
    assert row == ("add_to_cart", "campaign-7", "granted")
    with pytest.raises(ValueError, match="tenant_id"):
        record_marketing_event(db, fact | {"tenant_id": ""})


def test_invalid_signature_is_quarantined(db, monkeypatch):
    monkeypatch.setenv("MARKET_SOURCE_GA4_SECRET", "right-secret")
    fact = {
        "tenant_id": "tenant-a", "deduplication_id": "ga4:bad", "source_system": "ga4",
        "source_record_id": "bad", "event_type": "purchase",
        "occurred_at": "2026-07-20T01:00:00Z", "provenance_chain": ["ga4/bad"],
        "signature": "not-valid",
    }
    with pytest.raises(MarketFactRejected, match="invalid_source_signature"):
        record_marketing_event(db, fact)
    assert db.execute(text("SELECT reason_code FROM market_fact_quarantine")).scalar_one() == \
        "invalid_source_signature"


@pytest.mark.parametrize(
    ("patch", "reason"),
    [
        ({"provenance_chain": []}, "missing_provenance_chain"),
        ({"occurred_at": "2026-07-21T00:06:00Z"}, "event_time_in_future"),
        ({"occurred_at": "2026-07-13T00:00:00Z"}, "event_too_stale"),
        ({"source_system": "untrusted_scraper"}, "source_not_allowlisted"),
    ],
)
def test_untrusted_or_temporally_invalid_fact_is_quarantined(db, patch, reason):
    fact = {
        "tenant_id": "tenant-a", "deduplication_id": f"cart:{reason}",
        "source_system": "cart", "source_record_id": reason, "event_type": "view_item",
        "occurred_at": "2026-07-21T00:00:00Z", "provenance_chain": [f"cart/{reason}"],
    } | patch
    with pytest.raises(MarketFactRejected, match=reason):
        record_marketing_event(
            db, fact, now=datetime(2026, 7, 21, tzinfo=timezone.utc),
        )
    assert db.execute(text(
        "SELECT reason_code FROM market_fact_quarantine ORDER BY quarantined_at DESC LIMIT 1"
    )).scalar_one() == reason
