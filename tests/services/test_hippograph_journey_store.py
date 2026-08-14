from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.models.orm import (
    Base, HippographJourneyEdgeRecord, ProductAvailabilityObservation, ProductConfiguration,
)
from src.app.services.hippograph import HippoGraph
from src.app.services.hippograph_journey_edges import project_typed_journey_edges
from src.app.services.hippograph_journey_store import (
    load_configuration_availability_edges, load_journey_edges, persist_journey_edges,
)


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _edge(edge_id: str, when: str, **extra):
    return {
        "edge_id": edge_id, "tenant_id": "tenant-a", "source_id": "cfg:1",
        "source_kind": "configuration", "target_id": f"availability:{edge_id}",
        "target_kind": "availability_observation", "relation": "has_availability_observation",
        "signal_class": "observed", "evidence_id": f"ev:{edge_id}",
        "observed_at": when, "effective_at": when,
        "source_authority": "inventory_observation", **extra,
    }


def test_store_is_idempotent_tenant_scoped_and_replayable():
    db = _db()
    old = _edge("old", "2026-07-01T00:00:00Z")
    new = _edge("new", "2026-08-01T00:00:00Z", supersedes_edge_id="old")
    assert persist_journey_edges(db, [old, new], tenant_id="tenant-a", case_id="sc-1") == ["old", "new"]
    assert persist_journey_edges(db, [old], tenant_id="tenant-a", case_id="sc-1") == []
    assert db.query(HippographJourneyEdgeRecord).count() == 2

    loaded = load_journey_edges(db, tenant_id="tenant-a", case_id="sc-1")
    july = HippoGraph()
    receipt = project_typed_journey_edges(
        july, loaded, tenant_id="tenant-a", as_of="2026-07-15T00:00:00Z",
    )
    assert receipt.projected_edge_ids == ["old"]
    assert receipt.future_edge_ids == ["new"]


def test_store_rejects_cross_tenant_edges():
    db = _db()
    try:
        persist_journey_edges(db, [_edge("e1", datetime.now(timezone.utc).isoformat())], tenant_id="tenant-b")
    except ValueError as exc:
        assert str(exc) == "hippograph_edge_tenant_mismatch"
    else:
        raise AssertionError("cross-tenant edge was accepted")


def test_exact_configuration_availability_projects_as_observed_edge():
    db = _db()
    configuration = ProductConfiguration(
        id="cfg-1", tenant_id="tenant-a", sku="SKU-1", title="Exact laptop",
        configuration_hash="hash-1", form_factor="laptop", mobility="mobile",
        device_class="mobile_workstation", price_cents=300000, currency="AUD",
    )
    db.add(configuration)
    db.add(ProductAvailabilityObservation(
        id="availability-1", configuration_id="cfg-1", location_id="sydney",
        status="in_stock", quantity=5, lead_time_min_days=0, lead_time_max_days=1,
        source_record_id="inventory-receipt-1",
        observed_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
    ))
    db.commit()
    edges = load_configuration_availability_edges(db, tenant_id="tenant-a")
    assert len(edges) == 1
    assert edges[0].source_id == "configuration:cfg-1"
    assert edges[0].signal_class == "observed"
    assert edges[0].attributes["quantity"] == 5
    measurements = {row["metric"]: row for row in edges[0].attributes["evidence_measurements"]}
    assert measurements["availability_quantity"]["state"] == "observed"
    assert measurements["lead_time_min"]["value"] == 0


def test_missing_availability_fields_are_not_disclosed_not_zero():
    db = _db()
    db.add(ProductConfiguration(
        id="cfg-2", tenant_id="tenant-a", sku="SKU-2", title="Unknown availability",
        configuration_hash="hash-2", form_factor="laptop", mobility="mobile",
        device_class="mobile_workstation", price_cents=300000, currency="AUD",
    ))
    db.add(ProductAvailabilityObservation(
        id="availability-2", configuration_id="cfg-2", location_id="supplier",
        status="unknown", quantity=None, source_record_id="inventory-receipt-2",
        observed_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
    ))
    db.commit()
    edge = load_configuration_availability_edges(db, tenant_id="tenant-a")[0]
    measurements = {row["metric"]: row for row in edge.attributes["evidence_measurements"]}
    assert measurements["availability_quantity"]["state"] == "not_disclosed"
    assert measurements["availability_quantity"]["value"] is None
