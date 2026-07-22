from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.services.market_facts import record_marketing_event
from src.app.services.market_metrics import summarize_marketing_facts


MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260721_market_fact_contract.py"
GOVERNANCE = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260722_market_fact_governance.py"


def _db():
    spec = importlib.util.spec_from_file_location("market_fact_contract_metrics", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        spec2 = importlib.util.spec_from_file_location("market_fact_governance_metrics", GOVERNANCE)
        governance = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(governance)
        governance.op = Operations(MigrationContext.configure(connection))
        governance.upgrade()
    return sessionmaker(bind=engine)()


def test_summary_is_tenant_scoped_and_requires_sample_before_action():
    db = _db()
    try:
        for tenant in ("tenant-a", "tenant-b"):
            for user in range(3):
                for turn, event in enumerate(("view_item", "click", "add_to_cart", "purchase")):
                    record_marketing_event(db, {
                        "tenant_id": tenant, "deduplication_id": f"{tenant}:{user}:{turn}",
                        "source_system": "synthetic_lab", "source_record_id": f"{user}:{turn}",
                        "event_type": event, "occurred_at": f"2026-07-20T00:0{turn}:00Z",
                        "session_id": f"session-{user}", "sku": "SKU-1", "consent_state": "granted",
                        "provenance_chain": ["test"],
                    }, now=datetime(2026, 7, 21, tzinfo=timezone.utc))
        report = summarize_marketing_facts(db, tenant_id="tenant-a", min_action_sample=10)
        assert report["event_count"] == 12
        assert report["unique_sessions"] == 3
        assert report["funnel"]["cart_to_purchase_rate"] == 1.0
        assert report["insights"] == []
        assert report["data_quality"]["source_identity_rate"] == 1.0
        assert report["month_cohorts"]["2026-07"]["events"]["purchase"] == 3
        assert report["month_cohorts"]["2026-07"]["unique_sessions"] == 3
    finally:
        db.close()


def test_cart_abandonment_needs_denominator_and_is_operator_only():
    db = _db()
    try:
        for user in range(10):
            for turn, event in enumerate(("view_item", "click", "add_to_cart")):
                record_marketing_event(db, {
                    "tenant_id": "tenant-a", "deduplication_id": f"a:{user}:{turn}",
                    "source_system": "synthetic_lab", "source_record_id": f"{user}:{turn}",
                    "event_type": event, "occurred_at": f"2026-07-20T00:0{turn}:00Z",
                    "session_id": f"session-{user}", "sku": "SKU-1", "consent_state": "granted",
                    "provenance_chain": ["test"],
                }, now=datetime(2026, 7, 21, tzinfo=timezone.utc))
        report = summarize_marketing_facts(db, tenant_id="tenant-a")
        assert report["insights"][0]["type"] == "cart_abandonment"
        assert report["insights"][0]["authority"] == "operator_advisory"
        assert report["authority"] == "read_only_operator_advisory"
    finally:
        db.close()
