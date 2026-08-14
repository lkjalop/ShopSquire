from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.market_ingestion_observability import (
    connector_health,
    list_dead_letters,
    load_watermark,
    record_dead_letter,
    replay_dead_letter,
)
from src.app.services.market_signal import normalize
from src.app.services.market_signal_adapters import backfill_from_db_with_receipts
from tests.market_migration_helpers import apply_market_migration


MIGRATION = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260864_market_ingestion_observability.py"


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    db = sessionmaker(bind=engine, future=True)()
    apply_market_migration(db)
    spec = importlib.util.spec_from_file_location("market_ingestion_observability", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
    db.execute(text(
        "CREATE TABLE search_events (id TEXT, event_time TEXT, uid_hash TEXT, query TEXT, "
        "filters_json TEXT, result_skus_json TEXT, result_count INTEGER, view_mode TEXT, "
        "trace_id TEXT, session_id TEXT, tenant_id TEXT DEFAULT 'default')"
    ))
    db.execute(text(
        "INSERT INTO search_events (id,event_time,query,result_count,tenant_id) "
        "VALUES ('s1','2026-08-14T00:00:00Z','workstation',3,'tenant-a')"
    ))
    db.commit()
    return db


def test_backfill_persists_receipt_watermark_and_health_rates():
    db = _db()
    receipts = backfill_from_db_with_receipts(
        db, sources=["search_events"], tenant_id="tenant-a",
    )
    assert receipts[0].accepted == 1
    assert load_watermark(db, tenant_id="tenant-a", source="search_events") == "2026-08-14T00:00:00Z"
    health = connector_health(db, tenant_id="tenant-a")
    assert health["status"] == "observed"
    assert health["sources"][0]["failure_rate"] == 0
    assert health["sources"][0]["accepted_rate"] == 1
    assert health["sources"][0]["latency_ms_avg"] >= 0
    assert health["sources"][0]["watermark"] == "2026-08-14T00:00:00Z"
    assert health["sources"][0]["source_schema_version"] == 1

    db.execute(text(
        "INSERT INTO search_events (id,event_time,query,result_count,tenant_id) VALUES "
        "('older','2026-08-13T00:00:00Z','old',0,'tenant-a'),"
        "('newer','2026-08-15T00:00:00Z','new',2,'tenant-a')"
    ))
    db.commit()
    resumed = backfill_from_db_with_receipts(
        db, sources=["search_events"], tenant_id="tenant-a",
    )[0]
    assert resumed.watermark_before == "2026-08-14T00:00:00Z"
    assert resumed.rows_read == 1
    assert resumed.watermark_after == "2026-08-15T00:00:00Z"


def test_dead_letter_replay_is_explicit_and_policy_rejections_do_not_promote():
    db = _db()
    recoverable = normalize(
        signal_type="demand", source="manual_connector",
        payload={"event_id": "recoverable"}, occurred_at="2026-08-14T00:00:00Z",
        dedup_fields=["event_id"], tenant_id="tenant-a",
    )
    blocked = normalize(
        signal_type="demand", source="manual_connector",
        payload={"event_id": "blocked"}, occurred_at="2026-08-14T00:00:00Z",
        dedup_fields=["event_id"], tenant_id="tenant-a",
    )
    recoverable_id = record_dead_letter(
        db, tenant_id="tenant-a", source="manual_connector", signal=recoverable,
        reason_code="storage_failed",
    )
    blocked_id = record_dead_letter(
        db, tenant_id="tenant-a", source="manual_connector", signal=blocked,
        reason_code="low_trust",
    )
    db.commit()
    assert len(list_dead_letters(db, tenant_id="tenant-a")) == 2
    assert replay_dead_letter(
        db, tenant_id="tenant-a", dead_letter_id=blocked_id,
    )["status"] == "policy_rejection_requires_correction"
    replay = replay_dead_letter(db, tenant_id="tenant-a", dead_letter_id=recoverable_id)
    assert replay == {
        "status": "resolved", "accepted": True, "ingestion_status": "accepted",
        "authority": "operator_replay_only",
    }
