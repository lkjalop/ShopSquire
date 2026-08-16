from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.canonical_fact_adapters import (
    backfill_canonical_facts,
    canonical_source_health,
)


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
                    "sku TEXT, action TEXT, surface TEXT, trace_id TEXT, context_json TEXT, "
                    "tenant_id TEXT, consent_state TEXT)"))
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
    repeated = backfill_canonical_facts(db, tenant_id="tenant-a")
    assert repeated["quarantined"] == 0
    assert db.execute(text("SELECT COUNT(*) FROM market_fact_quarantine")).scalar_one() == 2
    health = canonical_source_health(db, tenant_id="tenant-a")
    assert health["active_records"] == 3
    assert health["quarantined_records"] == 2
    assert {row["family"] for row in health["sources"]} == {
        "inventory_atp",
        "marketing_event",
    }
    onboarding = {row["family"]: row for row in health["onboarding"]}
    assert onboarding["inventory_atp"]["status"] == "connected"
    assert onboarding["landed_inventory_valuation"]["status"] == "not_configured"
    assert "GMROI" in onboarding["landed_inventory_valuation"]["required_for"]
    assert onboarding["matched_procurement_documents"]["status"] == "not_configured"
    empty = canonical_source_health(db, tenant_id="tenant-b")
    assert empty["status"] == "unconfigured"
    assert all(row["status"] == "not_configured" for row in empty["onboarding"])
    db.close()


def test_multiline_order_without_line_prices_does_not_duplicate_order_total():
    db = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    _migration(db, "20260721_market_fact_contract.py", "fact_contract_multi")
    _migration(db, "20260722_market_fact_governance.py", "fact_governance_multi")
    _migration(db, "20260723_market_fact_quarantine_dedup.py", "fact_quarantine_multi")
    now = datetime.now(timezone.utc).isoformat()
    db.execute(text("CREATE TABLE orders (id TEXT, draft_order_id TEXT, customer_id TEXT, "
                    "guest_email_hash TEXT, total_cents INT, currency TEXT, status TEXT, "
                    "created_at TEXT, updated_at TEXT)"))
    db.execute(text("CREATE TABLE draft_orders (id TEXT, tenant_id TEXT, line_items TEXT)"))
    lines = json.dumps([
        {"sku": "SKU-1", "quantity": 1},
        {"sku": "SKU-2", "quantity": 1},
    ])
    db.execute(text("INSERT INTO draft_orders VALUES ('d1','tenant-a',:lines)"), {"lines": lines})
    db.execute(text("INSERT INTO orders VALUES "
                    "('o1','d1','u1',NULL,20000,'AUD','paid',:now,:now)"), {"now": now})
    db.commit()
    from src.app.services.canonical_fact_adapters import _order_facts
    assert _order_facts(db, "tenant-a", 10) == (2, 0)
    assert db.execute(text(
        "SELECT value FROM marketing_event_fact ORDER BY sku")).fetchall() == [(None,), (None,)]
    db.close()


def test_missing_source_timestamp_is_quarantined_not_replaced_with_ingestion_time():
    db = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    _migration(db, "20260721_market_fact_contract.py", "fact_contract_missing_time")
    _migration(db, "20260722_market_fact_governance.py", "fact_governance_missing_time")
    _migration(db, "20260723_market_fact_quarantine_dedup.py", "fact_quarantine_missing_time")
    db.execute(text("CREATE TABLE inventory_level (sku TEXT, tenant_id TEXT, location_id TEXT, "
                    "on_hand INT, reserved INT, available INT, source TEXT, updated_at TEXT)"))
    db.execute(text("INSERT INTO inventory_level VALUES "
                    "('SKU-1','tenant-a','SYD',7,2,5,'wms',NULL)"))
    db.commit()
    from src.app.services.canonical_fact_adapters import _inventory_facts
    assert _inventory_facts(db, "tenant-a", 10) == (0, 1)
    assert db.execute(text(
        "SELECT reason_code FROM market_fact_quarantine")).scalar_one() == "invalid_event_time"
    db.close()


def test_order_status_progression_does_not_duplicate_purchase():
    db = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    _migration(db, "20260721_market_fact_contract.py", "fact_contract_status")
    _migration(db, "20260722_market_fact_governance.py", "fact_governance_status")
    _migration(db, "20260723_market_fact_quarantine_dedup.py", "fact_quarantine_status")
    now = datetime.now(timezone.utc).isoformat()
    db.execute(text("CREATE TABLE orders (id TEXT, draft_order_id TEXT, customer_id TEXT, "
                    "guest_email_hash TEXT, total_cents INT, currency TEXT, status TEXT, "
                    "created_at TEXT, updated_at TEXT)"))
    db.execute(text("CREATE TABLE draft_orders (id TEXT, tenant_id TEXT, line_items TEXT)"))
    lines = json.dumps([{"sku": "SKU-1", "quantity": 2, "price_cents": 120000}])
    db.execute(text("INSERT INTO draft_orders VALUES ('d1','tenant-a',:lines)"), {"lines": lines})
    db.execute(text("INSERT INTO orders VALUES "
                    "('o1','d1','u1',NULL,240000,'AUD','paid',:now,:now)"), {"now": now})
    db.commit()

    from src.app.services.canonical_fact_adapters import _order_facts
    assert _order_facts(db, "tenant-a", 10) == (1, 0)
    db.execute(text("UPDATE orders SET status='delivered', updated_at=:now WHERE id='o1'"),
               {"now": now})
    db.commit()
    assert _order_facts(db, "tenant-a", 10) == (0, 0)
    assert db.execute(text(
        "SELECT COUNT(*) FROM marketing_event_fact WHERE event_type='purchase'"
    )).scalar_one() == 1
    db.close()


def test_monetary_order_without_currency_is_quarantined():
    db = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    _migration(db, "20260721_market_fact_contract.py", "fact_contract_currency")
    _migration(db, "20260722_market_fact_governance.py", "fact_governance_currency")
    _migration(db, "20260723_market_fact_quarantine_dedup.py", "fact_quarantine_currency")
    now = datetime.now(timezone.utc).isoformat()
    db.execute(text("CREATE TABLE orders (id TEXT, draft_order_id TEXT, customer_id TEXT, "
                    "guest_email_hash TEXT, total_cents INT, currency TEXT, status TEXT, "
                    "created_at TEXT, updated_at TEXT)"))
    db.execute(text("CREATE TABLE draft_orders (id TEXT, tenant_id TEXT, line_items TEXT)"))
    lines = json.dumps([{"sku": "SKU-1", "quantity": 1, "price_cents": 120000}])
    db.execute(text("INSERT INTO draft_orders VALUES ('d1','tenant-a',:lines)"), {"lines": lines})
    db.execute(text("INSERT INTO orders VALUES "
                    "('o1','d1','u1',NULL,120000,NULL,'paid',:now,:now)"), {"now": now})
    db.commit()

    from src.app.services.canonical_fact_adapters import _order_facts
    assert _order_facts(db, "tenant-a", 10) == (0, 1)
    assert db.execute(text(
        "SELECT reason_code FROM market_fact_quarantine")).scalar_one() == "missing_currency"
    db.close()


def test_source_health_distinguishes_broken_schema_from_unconfigured():
    db = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    health = canonical_source_health(db, tenant_id="tenant-a")
    assert health["status"] == "error"
    assert {item["family"] for item in health["source_errors"]} == {
        "inventory_atp", "marketing_event", "quarantine",
    }
    db.close()


def test_source_health_reports_only_tenant_scoped_sealed_forecast_pairs():
    db = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    _migration(db, "20260721_market_fact_contract.py", "fact_contract_forecast_health")
    _migration(db, "20260722_market_fact_governance.py", "fact_governance_forecast_health")
    _migration(db, "20260723_market_fact_quarantine_dedup.py", "fact_quarantine_forecast_health")
    _migration(db, "20260725_forecast_actual_pairs.py", "forecast_pairs_health")
    now = datetime.now(timezone.utc).isoformat()
    db.execute(text("""
        INSERT INTO forecast_actual_pair (
          id, tenant_id, pair_key, subject_type, subject_id, forecast_value,
          actual_value, unit, target_start, target_end, forecast_created_at,
          actual_observed_at, source_system, source_records_json, provenance_json,
          sealed_at, sealed_by, status
        ) VALUES
          ('p1','tenant-a','a1','sku','SKU-1',10,9,'units',:now,:now,:now,:now,
           'forecast_service','[]','[]',:now,'reviewer','active'),
          ('p2','tenant-b','b1','sku','SKU-1',10,9,'units',:now,:now,:now,:now,
           'forecast_service','[]','[]',:now,'reviewer','active'),
          ('p3','tenant-a','a2','sku','SKU-1',10,9,'units',:now,:now,:now,:now,
           'forecast_service','[]','[]',:now,'','active')
    """), {"now": now})
    db.commit()

    health = canonical_source_health(db, tenant_id="tenant-a")
    source = next(
        row for row in health["sources"]
        if row["family"] == "sealed_forecast_actual"
    )
    assert source["active_records"] == 1
    assert source["status"] == "healthy"
    onboarding = {row["family"]: row for row in health["onboarding"]}
    assert onboarding["sealed_forecast_actual"]["status"] == "connected"
    db.close()


def test_interaction_adapter_requires_affirmative_consent_and_preserves_event_type():
    db = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    _migration(db, "20260721_market_fact_contract.py", "fact_contract_consent")
    _migration(db, "20260722_market_fact_governance.py", "fact_governance_consent")
    _migration(db, "20260723_market_fact_quarantine_dedup.py", "fact_quarantine_consent")
    now = datetime.now(timezone.utc).isoformat()
    db.execute(text("CREATE TABLE recommend_interactions (id TEXT, event_time TEXT, uid_hash TEXT, "
                    "sku TEXT, action TEXT, surface TEXT, trace_id TEXT, context_json TEXT, "
                    "tenant_id TEXT, consent_state TEXT)"))
    db.execute(text("""
        INSERT INTO recommend_interactions VALUES
          ('g1',:now,'u1','SKU-1','hover','shelf','t1','{}','tenant-a','granted'),
          ('u1',:now,'u2','SKU-1','click','shelf','t2','{}','tenant-a','unknown'),
          ('d1',:now,'u3','SKU-1','impression','shelf','t3','{}','tenant-a','denied')
    """), {"now": now})
    db.commit()

    from src.app.services.canonical_fact_adapters import _interaction_facts

    assert _interaction_facts(db, "tenant-a", 10) == (1, 0)
    assert db.execute(text(
        "SELECT event_type,consent_state FROM marketing_event_fact"
    )).one() == ("hover", "granted")
    db.close()
