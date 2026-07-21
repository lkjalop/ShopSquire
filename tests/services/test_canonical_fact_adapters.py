from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.canonical_fact_adapters import backfill_canonical_facts


ROOT = Path(__file__).resolve().parents[2]


def _migration(db, filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "alembic" / "versions" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(db.connection()))
    module.upgrade()


def test_real_order_inventory_and_supplier_quote_materialize_canonical_facts():
    db = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    _migration(db, "20260721_market_fact_contract.py", "fact_contract")
    _migration(db, "20260722_market_fact_governance.py", "fact_governance")
    _migration(db, "20260723_market_fact_quarantine_dedup.py", "fact_quarantine_dedup")
    now = datetime.now(timezone.utc).isoformat()
    db.execute(text("CREATE TABLE orders (id TEXT, draft_order_id TEXT, customer_id TEXT, "
                    "guest_email_hash TEXT, total_cents INT, currency TEXT, status TEXT, "
                    "created_at TEXT, updated_at TEXT)"))
    db.execute(text("CREATE TABLE draft_orders (id TEXT, tenant_id TEXT, line_items TEXT)"))
    db.execute(text("CREATE TABLE recommend_interactions (id TEXT, event_time TEXT, uid_hash TEXT, "
                    "sku TEXT, action TEXT, surface TEXT, trace_id TEXT, context_json TEXT)"))
    db.execute(text("CREATE TABLE inventory_level (sku TEXT, tenant_id TEXT, location_id TEXT, "
                    "on_hand INT, reserved INT, available INT, source TEXT, updated_at TEXT)"))
    db.execute(text("CREATE TABLE fulfillment_case_version (id TEXT, case_id TEXT, tenant_id TEXT, "
                    "state_json TEXT, event TEXT, valid_from TEXT)"))
    lines = json.dumps([{"sku": "SKU-1", "quantity": 2, "price_cents": 120000}])
    db.execute(text("INSERT INTO draft_orders VALUES ('d1','tenant-a',:lines)"), {"lines": lines})
    db.execute(text("INSERT INTO orders VALUES ('o1','d1','u1',NULL,240000,'AUD','paid',:now,:now)"), {"now": now})
    db.execute(text("INSERT INTO inventory_level VALUES ('SKU-1','tenant-a','SYD',7,2,5,'wms',:now)"), {"now": now})
    state = json.dumps({"availability": {"item_ref": "SKU-1", "shortfall": 3},
                        "draft": {"commercial_scope": {"item_ref": "SKU-1", "quantity": 3}},
                        "validated_quote": {"quoted_quantity": 3, "lead_time_days": 6,
                                            "confidence": 0.95}})
    db.execute(text("INSERT INTO fulfillment_case_version VALUES "
                    "('v1','c1','tenant-a',:state,'supplier_quote_validated',:now)"),
               {"state": state, "now": now})
    db.commit()

    report = backfill_canonical_facts(db, tenant_id="tenant-a")
    assert report["errors"] == {}
    assert report["written"] == 3
    assert db.execute(text("SELECT COUNT(*) FROM marketing_event_fact")).scalar_one() == 1
    assert db.execute(text("SELECT COUNT(*) FROM inventory_atp_fact")).scalar_one() == 2
    assert backfill_canonical_facts(db, tenant_id="tenant-a")["written"] == 0

    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    db.execute(text("INSERT INTO inventory_level VALUES "
                    "('STALE-1','tenant-a','SYD',7,2,5,'wms',:stale),"
                    "('STALE-2','tenant-a','MEL',4,0,4,'wms',:stale)"), {"stale": stale})
    db.commit()
    rejected = backfill_canonical_facts(db, tenant_id="tenant-a")
    assert rejected["errors"] == {}
    assert rejected["quarantined_by_source"]["inventory"] == 2
    assert db.execute(text("SELECT COUNT(*) FROM market_fact_quarantine")).scalar_one() == 2
    backfill_canonical_facts(db, tenant_id="tenant-a")
    assert db.execute(text("SELECT COUNT(*) FROM market_fact_quarantine")).scalar_one() == 2
    db.close()
