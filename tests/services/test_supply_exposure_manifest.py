from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.supply_exposure_manifest import import_supply_exposure_manifest
from src.app.services.supply_graph_repository import bounded_dependency_paths


ROOT = Path(__file__).resolve().parents[2]


def _migrate(connection, filename: str) -> None:
    path = ROOT / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    with engine.begin() as connection:
        _migrate(connection, "20260817_supply_intelligence.py")
        _migrate(connection, "20260818_public_market_fetch.py")
        _migrate(connection, "20260821_supply_graph_ops.py")
    session = sessionmaker(bind=engine, future=True)()
    try:
        yield session
    finally:
        session.close()


def _manifest() -> dict:
    return {
        "schema_version": "supply_exposure.v1",
        "source_system": "tenant-approved-bom",
        "snapshot_id": "bom-2026-07",
        "revision": 1,
        "observed_at": "2026-07-01T00:00:00Z",
        "valid_from": "2026-07-01T00:00:00Z",
        "fresh_until": "2026-10-01T00:00:00Z",
        "provenance": {
            "document_id": "approved-bom-17",
            "licence": "tenant-owned",
        },
        "nodes": [
            {
                "logical_key": "index:copper",
                "node_type": "commodity_index",
                "label": "Copper benchmark",
            },
            {
                "logical_key": "material:copper",
                "node_type": "material",
                "label": "Copper",
            },
            {
                "logical_key": "component:power-board",
                "node_type": "component",
                "label": "Power board",
            },
            {
                "logical_key": "variant:device-au",
                "node_type": "variant",
                "label": "Device AU",
            },
            {
                "logical_key": "supplier:board-maker",
                "node_type": "supplier",
                "label": "Board Maker",
            },
            {
                "logical_key": "facility:board-maker-sz",
                "node_type": "facility",
                "label": "Board Maker Shenzhen",
            },
            {
                "logical_key": "location:au-dc",
                "node_type": "location",
                "label": "Sydney DC",
            },
        ],
        "edges": [
            {
                "logical_key": "copper-index-material",
                "from_logical_key": "index:copper",
                "to_logical_key": "material:copper",
                "relationship_type": "indexed_to",
                "confidence": 1.0,
            },
            {
                "logical_key": "copper-board",
                "from_logical_key": "material:copper",
                "to_logical_key": "component:power-board",
                "relationship_type": "composed_of",
                "confidence": 0.95,
                "properties": {"cost_share_low": 0.08, "cost_share_high": 0.16},
            },
            {
                "logical_key": "board-device",
                "from_logical_key": "component:power-board",
                "to_logical_key": "variant:device-au",
                "relationship_type": "composed_of",
                "confidence": 1.0,
            },
            {
                "logical_key": "device-supplier",
                "from_logical_key": "variant:device-au",
                "to_logical_key": "supplier:board-maker",
                "relationship_type": "supplied_by",
                "confidence": 1.0,
            },
            {
                "logical_key": "supplier-facility",
                "from_logical_key": "supplier:board-maker",
                "to_logical_key": "facility:board-maker-sz",
                "relationship_type": "manufactured_at",
                "confidence": 0.9,
            },
            {
                "logical_key": "facility-dc",
                "from_logical_key": "facility:board-maker-sz",
                "to_logical_key": "location:au-dc",
                "relationship_type": "transported_via",
                "confidence": 0.8,
            },
        ],
    }


def _node_id(db, tenant: str, key: str) -> str:
    return str(db.execute(text(
        "SELECT id FROM supply_node WHERE tenant_id=:tenant AND logical_key=:key "
        "AND recorded_to IS NULL"
    ), {"tenant": tenant, "key": key}).scalar_one())


def test_manifest_connects_market_material_component_variant_and_supplier_location(db):
    result = import_supply_exposure_manifest(
        db,
        tenant_id="tenant-a",
        manifest=_manifest(),
        approved_by="owner-1",
        imported_at="2026-07-02T00:00:00Z",
    )
    assert result["node_count"] == 7
    assert result["edge_count"] == 6
    assert result["authority"] == "advisory_only"
    assert result["execution_allowed"] is False
    assert result["manifest_hash"].startswith("sha256:")

    paths = bounded_dependency_paths(
        db,
        tenant_id="tenant-a",
        source_node_id=_node_id(db, "tenant-a", "index:copper"),
        target_node_id=_node_id(db, "tenant-a", "location:au-dc"),
        at="2026-08-01T00:00:00Z",
        max_depth=6,
    )
    assert len(paths["paths"]) == 1
    assert [edge["relationship_type"] for edge in paths["paths"][0]] == [
        "indexed_to",
        "composed_of",
        "composed_of",
        "supplied_by",
        "manufactured_at",
        "transported_via",
    ]


def test_manifest_replay_is_idempotent_and_tenant_isolated(db):
    first = import_supply_exposure_manifest(
        db,
        tenant_id="tenant-a",
        manifest=_manifest(),
        approved_by="owner-1",
        imported_at="2026-07-02T00:00:00Z",
    )
    replay = import_supply_exposure_manifest(
        db,
        tenant_id="tenant-a",
        manifest=_manifest(),
        approved_by="owner-1",
        imported_at="2026-07-03T00:00:00Z",
    )
    assert replay["manifest_hash"] == first["manifest_hash"]
    assert db.execute(text(
        "SELECT COUNT(*) FROM supply_node WHERE tenant_id='tenant-a'"
    )).scalar_one() == 7
    assert db.execute(text(
        "SELECT COUNT(*) FROM supply_node WHERE tenant_id='tenant-b'"
    )).scalar_one() == 0


def test_stale_or_future_manifest_fails_before_any_write(db):
    stale = _manifest()
    stale["fresh_until"] = "2026-07-02T00:00:00Z"
    with pytest.raises(ValueError, match="supply_exposure_manifest_stale"):
        import_supply_exposure_manifest(
            db,
            tenant_id="tenant-a",
            manifest=stale,
            approved_by="owner-1",
            imported_at="2026-08-01T00:00:00Z",
        )
    future = _manifest()
    future["observed_at"] = "2026-08-02T00:00:00Z"
    with pytest.raises(ValueError, match="supply_exposure_future_observation"):
        import_supply_exposure_manifest(
            db,
            tenant_id="tenant-a",
            manifest=future,
            approved_by="owner-1",
            imported_at="2026-08-01T00:00:00Z",
        )
    assert db.execute(text("SELECT COUNT(*) FROM supply_node")).scalar_one() == 0


def test_expired_exposure_edges_are_excluded_from_later_reasoning(db):
    import_supply_exposure_manifest(
        db,
        tenant_id="tenant-a",
        manifest=_manifest(),
        approved_by="owner-1",
        imported_at="2026-07-02T00:00:00Z",
    )
    paths = bounded_dependency_paths(
        db,
        tenant_id="tenant-a",
        source_node_id=_node_id(db, "tenant-a", "index:copper"),
        target_node_id=_node_id(db, "tenant-a", "variant:device-au"),
        at="2026-11-01T00:00:00Z",
    )
    assert paths["paths"] == []
    assert paths["stale_edge_count"] == 6
    assert paths["freshness_status"] == "degraded_stale_edges_excluded"
