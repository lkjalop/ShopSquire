from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.supply_mapping_registry import (
    register_supply_mapping,
    register_supply_relationship,
    resolve_supply_mapping,
    supply_mapping_health,
)


def _db():
    db = sessionmaker(bind=create_engine("sqlite://"))()
    db.execute(text("""CREATE TABLE tenant_supply_mapping (
      id TEXT PRIMARY KEY,tenant_id TEXT,mapping_type TEXT,external_id TEXT,canonical_id TEXT,
      source TEXT,source_version TEXT,observed_at TEXT,evidence_ref TEXT,confidence REAL,
      status TEXT,created_at TEXT)"""))
    db.execute(text("""CREATE TABLE tenant_supply_relationship (
      id TEXT PRIMARY KEY,tenant_id TEXT,relationship_type TEXT,subject_id TEXT,object_id TEXT,
      source TEXT,source_version TEXT,observed_at TEXT,evidence_ref TEXT,confidence REAL,
      status TEXT,created_at TEXT)"""))
    return db


def test_mapping_versions_are_tenant_scoped_append_only_and_source_healthy():
    db = _db()
    common = {"tenant_id": "t1", "source": "partner-master-data",
              "observed_at": "2026-08-02T00:00:00Z", "confidence": 1.0}
    first = register_supply_mapping(
        db, mapping_type="product", external_id="EXT-SKU", canonical_id="SKU-1",
        source_version="v1", evidence_ref="file:v1#2", **common,
    )
    replay = register_supply_mapping(
        db, mapping_type="product", external_id="EXT-SKU", canonical_id="SKU-1",
        source_version="v1", evidence_ref="file:v1#2", **common,
    )
    register_supply_mapping(
        db, mapping_type="product", external_id="EXT-SKU", canonical_id="SKU-2",
        source_version="v2", evidence_ref="file:v2#2",
        **(common | {"observed_at": "2026-08-02T01:00:00Z"}),
    )
    assert first["idempotent"] is False and replay["idempotent"] is True
    assert resolve_supply_mapping(
        db, tenant_id="t1", mapping_type="product", external_id="EXT-SKU",
    )["canonical_id"] == "SKU-2"
    assert db.execute(text(
        "SELECT COUNT(*) FROM tenant_supply_mapping WHERE external_id='EXT-SKU'"
    )).scalar() == 2
    health = supply_mapping_health(db, tenant_id="t1")
    assert health["status"] == "incomplete"
    assert health["missing_mapping_types"] == ["facility", "supplier"]


def test_qualified_substitute_is_a_versioned_relationship_not_an_identity_mapping():
    db = _db()
    first = register_supply_relationship(
        db, tenant_id="t1", relationship_type="qualified_substitute_for",
        subject_id="SKU-1", object_id="SKU-2", source="catalog-approval",
        source_version="v1", observed_at="2026-08-03T00:00:00Z",
        evidence_ref="approval:42", confidence=1.0,
    )
    replay = register_supply_relationship(
        db, tenant_id="t1", relationship_type="qualified_substitute_for",
        subject_id="SKU-1", object_id="SKU-2", source="catalog-approval",
        source_version="v1", observed_at="2026-08-03T00:00:00Z",
        evidence_ref="approval:42", confidence=1.0,
    )

    assert first["idempotent"] is False and replay["idempotent"] is True
    assert db.execute(text("SELECT COUNT(*) FROM tenant_supply_mapping")).scalar() == 0
    assert db.execute(text("SELECT COUNT(*) FROM tenant_supply_relationship")).scalar() == 1
