from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.search_demand_authority import (
    append_search_observation,
    project_search_demand_authority,
)


def _db():
    engine = create_engine("sqlite:///:memory:", future=True)
    db = sessionmaker(bind=engine, future=True)()
    db.execute(text("""
        CREATE TABLE search_demand_observation (
          id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, trace_id TEXT NOT NULL,
          case_id TEXT, session_epoch TEXT NOT NULL, actor_hash TEXT NOT NULL,
          actor_dedup_class TEXT NOT NULL, abuse_status TEXT NOT NULL,
          requirement_fingerprint TEXT NOT NULL, query_hash TEXT NOT NULL,
          resolved_sku TEXT, unresolved_concept TEXT, requested_quantity INTEGER,
          qualification_outcome TEXT NOT NULL, evidence_refs_json TEXT NOT NULL,
          source_policy_status TEXT NOT NULL, lifecycle_stage TEXT NOT NULL,
          authority TEXT NOT NULL, inventory_snapshot_json TEXT NOT NULL,
          observed_at TEXT NOT NULL, effective_at TEXT NOT NULL,
          supersedes_id TEXT, simulation_only BOOLEAN NOT NULL, created_at TEXT NOT NULL
        )
    """))
    db.commit()
    return db


def test_unresolved_search_is_interest_not_demand() -> None:
    db = _db()
    row = append_search_observation(
        db,
        tenant_id="tenant-a",
        trace_id="trace-1",
        session_epoch="epoch-1",
        actor_hash="actor-1",
        query="30 laptops capable of engine digital-twin simulations",
        requirement={"product_type": "portable computer", "workload": "digital twin"},
        requested_quantity=30,
        unresolved_concept="digital twin",
        qualification_outcome="blocked",
        lifecycle_stage="clarification_requested",
        source_policy_status="not_evaluated",
        simulation_only=True,
    )
    assert row["authority"] == "interest"
    projection = project_search_demand_authority(db, tenant_id="tenant-a")
    assert projection["search_interest_count"] == 1
    assert projection["qualified_searches"] == 0
    assert projection["committed_demand_units"] == 0
    assert projection["projected_revenue"] is None
    assert projection["inventory_action_allowed"] is False
    assert projection["forecast_influence"] == "shadow_only"
    assert projection["observation_authority"] == "simulation"


def test_empty_projection_does_not_claim_live_observations() -> None:
    projection = project_search_demand_authority(_db(), tenant_id="tenant-a")
    assert projection["observation_authority"] == "no_observations"


def test_lifecycle_counts_latest_authority_once_and_joins_snapshot() -> None:
    db = _db()
    first = append_search_observation(
        db, tenant_id="tenant-a", trace_id="trace-2", case_id="case-2",
        session_epoch="epoch-2", actor_hash="actor-2", query="30 qualified laptops",
        requirement={"sku": "SKU-1", "quantity": 30}, resolved_sku="SKU-1",
        requested_quantity=30, qualification_outcome="qualified",
        lifecycle_stage="qualified_interest", evidence_refs=["citation-1"],
        source_policy_status="approved", simulation_only=True,
        inventory_snapshot={
            "confirmed_atp": 12, "transferable": 8, "unconfirmed_shortfall": 10,
            "source_version": "ATP-2026-08-05-14",
            "observed_at": "2026-08-05T14:02:00+10:00", "freshness_status": "fresh",
        },
    )
    append_search_observation(
        db, tenant_id="tenant-a", trace_id="trace-2", case_id="case-2",
        session_epoch="epoch-2", actor_hash="actor-2", query="commit the 30 laptops",
        requirement={"sku": "SKU-1", "quantity": 30}, resolved_sku="SKU-1",
        requested_quantity=30, qualification_outcome="qualified",
        lifecycle_stage="buyer_commitment", evidence_refs=["citation-1"],
        source_policy_status="approved", supersedes_id=first["id"], simulation_only=True,
        inventory_snapshot={
            "confirmed_atp": 12, "transferable": 8, "unconfirmed_shortfall": 10,
            "source_version": "ATP-2026-08-05-14",
            "observed_at": "2026-08-05T14:02:00+10:00", "freshness_status": "fresh",
        },
    )
    projection = project_search_demand_authority(db, tenant_id="tenant-a")
    assert projection["qualified_searches"] == 1
    assert projection["committed_demand_units"] == 30
    assert projection["confirmed_atp_units"] == 12
    assert projection["transferable_units"] == 8
    assert projection["qualified_unmet_units"] == 10
    assert projection["inventory_source_versions"] == ["ATP-2026-08-05-14"]


def test_cross_tenant_and_repeated_actor_signals_do_not_merge() -> None:
    db = _db()
    for tenant in ("tenant-a", "tenant-b"):
        append_search_observation(
            db, tenant_id=tenant, trace_id=f"trace-{tenant}", session_epoch="epoch",
            actor_hash="same-hash", query="rare product", requirement={"concept": "rare"},
            qualification_outcome="no_match", lifecycle_stage="search_interest",
            actor_dedup_class="repeated_actor", abuse_status="review_required",
        )
    a = project_search_demand_authority(db, tenant_id="tenant-a")
    assert a["search_interest_count"] == 1
    assert a["eligible_forecast_signal_count"] == 0


def test_stage_cannot_claim_stronger_authority_than_lifecycle() -> None:
    db = _db()
    row = append_search_observation(
        db, tenant_id="tenant-a", trace_id="trace-3", session_epoch="epoch-3",
        actor_hash="actor-3", query="show laptops", requirement={"category": "laptop"},
        qualification_outcome="no_match", lifecycle_stage="search_interest",
        authority="committed",
    )
    assert row["authority"] == "interest"
