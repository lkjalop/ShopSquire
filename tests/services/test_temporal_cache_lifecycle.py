from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.semantic_cache import SemanticCache
from src.app.services.temporal_invalidation import (
    invalidate_source_and_schedule_rebuild,
    register_cache_dependency,
)


def _db():
    db = sessionmaker(bind=create_engine("sqlite://"))()
    db.execute(text("""CREATE TABLE temporal_dependency (
      id TEXT PRIMARY KEY,tenant_id TEXT,source_type TEXT,source_id TEXT,source_version TEXT,
      derived_type TEXT,derived_id TEXT,status TEXT,created_at TEXT,invalidated_at TEXT,
      invalidation_reason TEXT,
      UNIQUE(tenant_id,source_type,source_id,source_version,derived_type,derived_id))"""))
    return db


def test_supersession_evicts_exact_cache_entry_and_enqueues_one_rebuild():
    db = _db()
    cache = SemanticCache()
    cache.set("cache:v2:test:key", {"stale": True})
    register_cache_dependency(
        db, tenant_id="tenant-a", cache_key="cache:v2:test:key",
        source_type="market_evidence", source_id="evidence-1", source_version="rev-1",
    )
    jobs = []

    first = invalidate_source_and_schedule_rebuild(
        db, tenant_id="tenant-a", source_type="market_evidence",
        source_id="evidence-1", source_version="rev-1", reason="superseded",
        cache=cache, enqueue_rebuild=jobs.append,
    )
    replay = invalidate_source_and_schedule_rebuild(
        db, tenant_id="tenant-a", source_type="market_evidence",
        source_id="evidence-1", source_version="rev-1", reason="superseded",
        cache=cache, enqueue_rebuild=jobs.append,
    )

    assert cache.get("cache:v2:test:key") is None
    assert first["cache_entries_evicted"] == 1
    assert first["rebuilds_enqueued"] == 1
    assert replay["cache_entries_evicted"] == 0
    assert replay["rebuilds_enqueued"] == 0
    assert jobs == [{
        "job_type": "rebuild_temporal_cache_entry",
        "tenant_id": "tenant-a",
        "cache_key": "cache:v2:test:key",
        "source_type": "market_evidence",
        "source_id": "evidence-1",
        "source_version": "rev-1",
        "reason": "superseded",
    }]
