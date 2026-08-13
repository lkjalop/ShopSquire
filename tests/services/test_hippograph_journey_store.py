from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.models.orm import Base, HippographJourneyEdgeRecord
from src.app.services.hippograph import HippoGraph
from src.app.services.hippograph_journey_edges import project_typed_journey_edges
from src.app.services.hippograph_journey_store import load_journey_edges, persist_journey_edges


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
