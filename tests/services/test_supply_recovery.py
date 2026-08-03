from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.supply_recovery import project_supply_recovery


def _db():
    db = sessionmaker(bind=create_engine("sqlite://"))()
    db.execute(text("CREATE TABLE suppliers (id TEXT PRIMARY KEY,name TEXT,reliability_score REAL,active INTEGER)"))
    db.execute(text("CREATE TABLE supplier_products (supplier_id TEXT,sku TEXT)"))
    db.execute(text("CREATE TABLE trusted_supplier_domains (id TEXT,domain TEXT,supplier_id TEXT,active INTEGER)"))
    db.execute(text("""CREATE TABLE tenant_supply_mapping (
      id TEXT PRIMARY KEY,tenant_id TEXT,mapping_type TEXT,external_id TEXT,canonical_id TEXT,
      source TEXT,source_version TEXT,observed_at TEXT,evidence_ref TEXT,confidence REAL,status TEXT)"""))
    db.execute(text("""CREATE TABLE tenant_supply_relationship (
      id TEXT PRIMARY KEY,tenant_id TEXT,relationship_type TEXT,subject_id TEXT,object_id TEXT,
      source TEXT,source_version TEXT,observed_at TEXT,evidence_ref TEXT,confidence REAL,status TEXT)"""))
    db.execute(text("INSERT INTO suppliers VALUES ('PRIMARY','Primary',0.9,1),('ALT','Alternative',0.95,1),('SUBSUP','Substitute supplier',0.88,1)"))
    db.execute(text("INSERT INTO supplier_products VALUES ('PRIMARY','SKU-1'),('ALT','SKU-1'),('SUBSUP','SKU-2')"))
    db.execute(text("INSERT INTO trusted_supplier_domains VALUES ('d1','primary.test','PRIMARY',1),('d2','alt.test','ALT',1),('d3','sub.test','SUBSUP',1)"))
    observed = "2026-08-03T00:00:00Z"
    db.execute(text("""INSERT INTO tenant_supply_mapping VALUES
      ('m1','t1','supplier','ERP-ALT','ALT','tenant-master','v1',:o,'file:v1#2',1.0,'active')"""), {"o": observed})
    db.execute(text("""INSERT INTO tenant_supply_relationship VALUES
      ('r1','t1','qualified_substitute_for','SKU-1','SKU-2','approved-substitutes','v3',:o,'approval:42',1.0,'active')"""), {"o": observed})
    return db


def test_recovery_only_exposes_fresh_tenant_approved_candidates_as_unknown():
    result = project_supply_recovery(
        _db(), tenant_id="t1", sku="SKU-1", excluded_supplier_id="PRIMARY",
        now=datetime(2026, 8, 3, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "options_available"
    assert result["alternative_suppliers"][0]["supplier_id"] == "ALT"
    assert result["alternative_suppliers"][0]["availability"] == "unknown"
    assert result["qualified_substitutes"][0]["sku"] == "SKU-2"
    assert result["qualified_substitutes"][0]["qualification"] == "tenant_approved_mapping"
    assert result["external_action"] == "none"
    assert result["state_prevented"] == "unconfirmed_supply_presented_as_available"


def test_recovery_fails_closed_without_tenant_mapping_authority():
    db = _db()
    db.execute(text("DELETE FROM tenant_supply_mapping"))
    db.execute(text("DELETE FROM tenant_supply_relationship"))

    result = project_supply_recovery(
        db, tenant_id="t1", sku="SKU-1", excluded_supplier_id="PRIMARY",
        now=datetime(2026, 8, 3, 1, tzinfo=timezone.utc),
    )

    assert result["status"] == "insufficient_evidence"
    assert result["alternative_suppliers"] == []
    assert result["qualified_substitutes"] == []
