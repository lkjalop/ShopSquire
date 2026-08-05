from __future__ import annotations

import inspect
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services import search_events
from src.app.services.search_demand_authority import project_search_demand_authority


def test_search_event_writer_is_migration_first_and_projects_canonical_authority(monkeypatch) -> None:
    assert "CREATE TABLE" not in inspect.getsource(search_events.ensure_search_events_table).upper()
    engine = create_engine("sqlite:///:memory:", future=True)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as db:
        db.execute(text("""
            CREATE TABLE search_events (
              id TEXT PRIMARY KEY, event_time TEXT DEFAULT CURRENT_TIMESTAMP,
              uid_hash TEXT, query TEXT, filters_json TEXT, result_skus_json TEXT,
              result_count INTEGER, view_mode TEXT, trace_id TEXT, session_id TEXT
            )
        """))
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

    @contextmanager
    def scoped_session():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(search_events, "db_session", scoped_session)
    event_id = search_events.log_search_event(
        uid="buyer-1", query="30 laptops for digital twins", filters={}, result_skus=[],
        view_mode="grid", trace_id="trace-1", session_id="session-1",
        tenant_id="tenant-a", session_epoch="epoch-1",
        requirement={"workload": "digital twin", "quantity": 30},
        requested_quantity=30, qualification_outcome="blocked",
        lifecycle_stage="clarification_requested", unresolved_concept="digital twin",
        source_policy_status="not_evaluated", actor_dedup_class="distinct_actor",
        abuse_status="not_evaluated", simulation_only=True,
    )
    assert event_id
    with factory() as db:
        projection = project_search_demand_authority(db, tenant_id="tenant-a")
    assert projection["search_interest_count"] == 1
    assert projection["committed_demand_units"] == 0
    assert projection["inventory_action_allowed"] is False
