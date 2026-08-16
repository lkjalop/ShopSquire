from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.market_source_registry import govern_external_observation
from src.app.services.supply_graph_repository import (
    approve_subject_mapping,
    bounded_dependency_paths,
    graph_quality,
    project_public_observations,
    public_source_health,
    put_edge_revision,
    put_node_revision,
)


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


def _node(db, tenant: str, key: str, kind: str = "component"):
    return put_node_revision(
        db,
        tenant_id=tenant,
        logical_key=key,
        node_type=kind,
        label=key,
        source_system="operator",
        source_record_id=key,
        provenance={"actor": "owner-1"},
        valid_from="2026-01-01T00:00:00Z",
    )


def test_migration_adds_revision_mapping_and_quarantine_tables(db):
    tables = set(inspect(db.bind).get_table_names())
    assert {"market_subject_mapping", "supply_signal_quarantine"} <= tables
    columns = {
        column["name"] for column in inspect(db.bind).get_columns("supply_node")
    }
    assert {"logical_key", "recorded_from", "recorded_to", "supersedes_id"} <= columns


def test_node_and_edge_revisions_are_bitemporal_and_relationships_validated(db):
    material = _node(db, "tenant-a", "material:aluminium", "material")
    product = _node(db, "tenant-a", "variant:frame", "variant")
    first = put_edge_revision(
        db,
        tenant_id="tenant-a",
        logical_key="composition:frame:aluminium",
        from_node_id=material["id"],
        to_node_id=product["id"],
        relationship_type="composed_of",
        source_system="bom",
        source_record_id="bom-1",
        provenance={"document": "bom-v1"},
        valid_from="2026-01-01T00:00:00Z",
        confidence=0.8,
        properties={"cost_share_low": 0.1, "cost_share_high": 0.2},
    )
    second = put_edge_revision(
        db,
        tenant_id="tenant-a",
        logical_key="composition:frame:aluminium",
        from_node_id=material["id"],
        to_node_id=product["id"],
        relationship_type="composed_of",
        source_system="bom",
        source_record_id="bom-2",
        provenance={"document": "bom-v2"},
        valid_from="2026-03-01T00:00:00Z",
        confidence=0.95,
        revision_reason="corrected_bom",
    )
    assert second["supersedes_id"] == first["id"]
    closed = db.execute(text(
        "SELECT recorded_to,valid_to FROM supply_dependency_edge WHERE id=:id"
    ), {"id": first["id"]}).mappings().one()
    assert closed["recorded_to"] is not None
    assert closed["valid_to"] is not None
    with pytest.raises(ValueError, match="supply_relationship_type_invalid"):
        put_edge_revision(
            db,
            tenant_id="tenant-a",
            logical_key="bad",
            from_node_id=material["id"],
            to_node_id=product["id"],
            relationship_type="probably_related_to",
            source_system="guess",
            source_record_id="guess",
            provenance={"actor": "model"},
            valid_from="2026-01-01T00:00:00Z",
            confidence=0.2,
        )


def test_path_replay_uses_effective_and_known_time_without_future_leakage(db):
    source = _node(db, "tenant-a", "supplier:one", "supplier")
    target = _node(db, "tenant-a", "warehouse:syd", "warehouse")
    first = put_edge_revision(
        db, tenant_id="tenant-a", logical_key="lane:one",
        from_node_id=source["id"], to_node_id=target["id"],
        relationship_type="delivers_to", source_system="carrier",
        source_record_id="lane-v1", provenance={"schedule": "v1"},
        valid_from="2026-01-01T00:00:00Z", recorded_at="2026-01-02T00:00:00Z",
        confidence=1.0, properties={"lead_time_days_p50": 8},
    )
    second = put_edge_revision(
        db, tenant_id="tenant-a", logical_key="lane:one",
        from_node_id=source["id"], to_node_id=target["id"],
        relationship_type="delivers_to", source_system="carrier",
        source_record_id="lane-v2", provenance={"schedule": "v2"},
        valid_from="2026-03-01T00:00:00Z", recorded_at="2026-04-01T00:00:00Z",
        confidence=1.0, properties={"lead_time_days_p50": 3},
    )

    historical = bounded_dependency_paths(
        db, tenant_id="tenant-a", source_node_id=source["id"],
        target_node_id=target["id"], effective_at="2026-02-01T00:00:00Z",
        known_at="2026-02-01T00:00:00Z",
    )
    current = bounded_dependency_paths(
        db, tenant_id="tenant-a", source_node_id=source["id"],
        target_node_id=target["id"], effective_at="2026-05-01T00:00:00Z",
        known_at="2026-05-01T00:00:00Z",
    )

    assert historical["paths"][0][0]["id"] == first["id"]
    assert current["paths"][0][0]["id"] == second["id"]


def test_source_record_replay_is_idempotent_and_does_not_create_revision(db):
    first = _node(db, "tenant-a", "material:copper", "material")
    replay = _node(db, "tenant-a", "material:copper", "material")
    assert replay["id"] == first["id"]
    assert replay["idempotent_replay"] is True
    count = db.execute(text(
        "SELECT COUNT(*) FROM supply_node WHERE tenant_id='tenant-a'"
    )).scalar_one()
    assert count == 1


def test_paths_are_bounded_and_tenant_scoped(db):
    source = _node(db, "tenant-a", "index:aluminium", "commodity_index")
    material = _node(db, "tenant-a", "material:aluminium", "material")
    target = _node(db, "tenant-a", "variant:frame", "variant")
    for key, left, right, relationship in (
        ("indexed", source, material, "indexed_to"),
        ("composed", material, target, "composed_of"),
    ):
        put_edge_revision(
            db,
            tenant_id="tenant-a",
            logical_key=key,
            from_node_id=left["id"],
            to_node_id=right["id"],
            relationship_type=relationship,
            source_system="operator",
            source_record_id=key,
            provenance={"actor": "owner-1"},
            valid_from="2026-01-01T00:00:00Z",
            confidence=0.9,
        )
    result = bounded_dependency_paths(
        db,
        tenant_id="tenant-a",
        source_node_id=source["id"],
        target_node_id=target["id"],
        at="2026-06-01T00:00:00Z",
        max_depth=2,
    )
    assert len(result["paths"]) == 1
    assert len(result["paths"][0]) == 2
    isolated = bounded_dependency_paths(
        db,
        tenant_id="tenant-b",
        source_node_id=source["id"],
        target_node_id=target["id"],
    )
    assert isolated["paths"] == []


def test_quality_reports_incomplete_identity_and_supplier_concentration(db):
    variant = _node(db, "tenant-a", "variant:a", "variant")
    supplier = _node(db, "tenant-a", "supplier:a", "supplier")
    put_edge_revision(
        db,
        tenant_id="tenant-a",
        logical_key="supplier:a",
        from_node_id=variant["id"],
        to_node_id=supplier["id"],
        relationship_type="supplied_by",
        source_system="contract",
        source_record_id="contract-a",
        provenance={"contract": "a"},
        valid_from="2026-01-01T00:00:00Z",
        confidence=1.0,
        properties={"attributable_spend_minor": 125000},
    )
    put_node_revision(
        db,
        tenant_id="tenant-a",
        logical_key="material:unknown",
        node_type="material",
        label="Unresolved alloy",
        source_system="invoice",
        source_record_id="line-1",
        provenance={"invoice": "1"},
        valid_from="2026-01-01T00:00:00Z",
        identity_status="unresolved",
    )
    quality = graph_quality(db, tenant_id="tenant-a")
    assert quality["dependency_completeness"] == 1.0
    assert quality["supplier_concentration_hhi"] == 1.0
    assert quality["supplier_spend_concentration_hhi"] == 1.0
    assert quality["attributable_supplier_spend_minor"] == 125000
    assert quality["supplier_spend_concentration_status"] == "observed"
    assert quality["unresolved_identity_count"] == 1
    assert quality["status"] == "incomplete"


def _observation(subject: str, record: str = "Aluminum:2026M06"):
    return govern_external_observation(
        source_id="world_bank_pink_sheet",
        source_record_id=record,
        signal_type="commodity_input_price",
        subject_id=subject,
        measurement={
            "kind": "commodity_benchmark_price",
            "direction": "increase",
            "value": 2500.0,
            "currency": "USD",
            "uom": "$/mt",
            "supply_chain_stage": "commodity_benchmark",
        },
        geography="global_benchmark",
        effective_from="2026-06-01T00:00:00Z",
        effective_to=None,
        published_at="2026-07-02T00:00:00Z",
        available_at="2026-07-02T00:00:00Z",
        retrieved_at="2026-07-03T00:00:00Z",
    )


def test_public_observation_requires_exact_approved_mapping(db):
    node = _node(db, "tenant-a", "index:aluminium", "commodity_index")
    observation = _observation("world-bank-commodity:aluminum")
    missing = project_public_observations(
        db,
        tenant_id="tenant-a",
        source_id="world_bank_pink_sheet",
        source_revision=1,
        observations=[observation],
        fresh_until="2026-08-01T00:00:00Z",
    )
    assert missing["projected"] == 0
    assert missing["quarantine_reasons"] == {"subject_mapping_missing": 1}
    approve_subject_mapping(
        db,
        tenant_id="tenant-a",
        source_id="world_bank_pink_sheet",
        external_subject_id=observation["subject_id"],
        subject_node_id=node["id"],
        mapping_basis="operator_verified_series_identity",
        provenance={"registry": "pink-sheet-v1"},
        approved_by="owner-1",
        valid_from="2026-01-01T00:00:00Z",
    )
    projected = project_public_observations(
        db,
        tenant_id="tenant-a",
        source_id="world_bank_pink_sheet",
        source_revision=2,
        observations=[observation],
        fresh_until="2026-08-01T00:00:00Z",
    )
    assert projected["projected"] == 1
    signal = db.execute(text(
        "SELECT subject_node_id,status,mapping_id,comparison_scope_json "
        "FROM supply_signal_observation WHERE tenant_id='tenant-a'"
    )).mappings().one()
    assert signal["subject_node_id"] == node["id"]
    assert signal["status"] == "observed"
    assert signal["mapping_id"]
    assert '"supply_chain_stage":"commodity_benchmark"' in signal[
        "comparison_scope_json"
    ]


def test_ambiguous_subject_mapping_is_quarantined(db):
    observation = _observation("world-bank-commodity:aluminum", "Aluminum:2026M07")
    for key in ("index:aluminium-a", "index:aluminium-b"):
        node = _node(db, "tenant-a", key, "commodity_index")
        approve_subject_mapping(
            db,
            tenant_id="tenant-a",
            source_id="world_bank_pink_sheet",
            external_subject_id=observation["subject_id"],
            subject_node_id=node["id"],
            mapping_basis="conflicting_operator_mapping",
            provenance={"ticket": key},
            approved_by="owner-1",
        )
    result = project_public_observations(
        db,
        tenant_id="tenant-a",
        source_id="world_bank_pink_sheet",
        source_revision=1,
        observations=[observation],
        fresh_until=None,
    )
    assert result["projected"] == 0
    assert result["quarantine_reasons"] == {"subject_mapping_ambiguous": 1}


def test_source_health_distinguishes_fresh_stale_and_never_fetched(db):
    never = public_source_health(
        db, tenant_id="tenant-a", source_id="cpsc_recalls",
    )
    assert never["status"] == "never_fetched"
    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    db.execute(text(
        "INSERT INTO market_source_fetch_revision "
        "(id,tenant_id,source_id,request_key,revision_number,request_json,outcome,"
        "source_policy_json,retrieved_at,expires_at) VALUES "
        "('f1','tenant-a','cpsc_recalls','key',1,'{}','observed','{}',"
        ":retrieved,:expires)"
    ), {"retrieved": now - timedelta(hours=1), "expires": now + timedelta(hours=1)})
    db.commit()
    fresh = public_source_health(
        db, tenant_id="tenant-a", source_id="cpsc_recalls", now=now,
    )
    assert fresh["status"] == "healthy"
    stale = public_source_health(
        db,
        tenant_id="tenant-a",
        source_id="cpsc_recalls",
        now=now + timedelta(hours=2),
    )
    assert stale["status"] == "stale"
