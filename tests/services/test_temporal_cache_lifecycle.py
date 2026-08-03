from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.semantic_cache import SemanticCache
from src.app.services.temporal_invalidation import (
    cache_lifecycle,
    claim_cache_rebuild,
    complete_cache_rebuild,
    fail_cache_rebuild,
    invalidate_source_and_schedule_rebuild,
    mark_cache_stale,
    read_current_cache,
    register_cache_dependency,
    tenant_cache_lifecycle_projection,
    supersede_cache_entry,
)
from src.app.services.temporal_cache_rebuild import (
    dispatch_queued_rebuilds,
    execute_cache_rebuild,
    register_rebuild_handler,
    unregister_rebuild_handler,
)


def _db():
    db = sessionmaker(bind=create_engine("sqlite://"))()
    db.execute(text("""CREATE TABLE temporal_dependency (
      id TEXT PRIMARY KEY,tenant_id TEXT,source_type TEXT,source_id TEXT,source_version TEXT,
      derived_type TEXT,derived_id TEXT,status TEXT,created_at TEXT,invalidated_at TEXT,
      invalidation_reason TEXT,
      UNIQUE(tenant_id,source_type,source_id,source_version,derived_type,derived_id))"""))
    db.execute(text("""CREATE TABLE temporal_cache_entry (
      id TEXT PRIMARY KEY,tenant_id TEXT,cache_key TEXT,namespace TEXT,status TEXT,
      current_generation INTEGER,pending_generation INTEGER,last_error TEXT,created_at TEXT,
      updated_at TEXT,UNIQUE(tenant_id,cache_key))"""))
    db.execute(text("""CREATE TABLE temporal_cache_generation (
      id TEXT PRIMARY KEY,entry_id TEXT,generation INTEGER,storage_key TEXT,content_hash TEXT,
      status TEXT,created_at TEXT,published_at TEXT,superseded_at TEXT,
      UNIQUE(entry_id,generation))"""))
    db.execute(text("""CREATE TABLE temporal_cache_rebuild_job (
      id TEXT PRIMARY KEY,tenant_id TEXT,entry_id TEXT,cache_key TEXT,idempotency_key TEXT,
      status TEXT,source_type TEXT,source_id TEXT,source_version TEXT,reason TEXT,attempts INTEGER,
      dispatch_attempts INTEGER DEFAULT 0,created_at TEXT,dispatched_at TEXT,started_at TEXT,
      finished_at TEXT,last_error TEXT,
      UNIQUE(tenant_id,idempotency_key))"""))
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
    assert len(jobs) == 1
    assert jobs[0] == {
        "job_type": "rebuild_temporal_cache_entry",
        "job_id": jobs[0]["job_id"],
        "tenant_id": "tenant-a",
        "cache_key": "cache:v2:test:key",
        "source_type": "market_evidence",
        "source_id": "evidence-1",
        "source_version": "rev-1",
        "reason": "superseded",
    }


def test_invalidated_generation_is_not_servable_even_if_provider_delete_fails():
    db = _db()

    class DeleteFailsCache(SemanticCache):
        def delete(self, key: str) -> None:
            raise RuntimeError("redis unavailable")

    cache = DeleteFailsCache()
    cache.set("cache:v2:faq:test", {"stale": True})
    register_cache_dependency(
        db, tenant_id="tenant-a", cache_key="cache:v2:faq:test",
        source_type="faq_corpus", source_id="faq", source_version="v1",
    )
    assert read_current_cache(
        db, tenant_id="tenant-a", cache_key="cache:v2:faq:test", cache=cache,
    ) == {"stale": True}

    result = invalidate_source_and_schedule_rebuild(
        db, tenant_id="tenant-a", source_type="faq_corpus", source_id="faq",
        source_version="v1", reason="superseded", cache=cache,
    )

    # The database authority changed before the provider eviction was attempted.
    assert read_current_cache(
        db, tenant_id="tenant-a", cache_key="cache:v2:faq:test", cache=cache,
    ) is None
    assert cache_lifecycle(
        db, tenant_id="tenant-a", cache_key="cache:v2:faq:test",
    )["status"] == "rebuild_queued"
    assert result["cache_eviction_failures"] == [
        {"cache_key": "cache:v2:faq:test", "error": "RuntimeError"}
    ]
    assert result["rebuilds_enqueued"] == 1


def test_rebuild_publishes_new_generation_atomically_and_replay_is_idempotent():
    db = _db()
    cache = SemanticCache()
    old_key = "cache:v2:faq:test"
    new_key = f"{old_key}:generation:2"
    cache.set(old_key, {"answer": "old"})
    register_cache_dependency(
        db, tenant_id="tenant-a", cache_key=old_key,
        source_type="faq_corpus", source_id="faq", source_version="v1",
    )
    jobs = []
    invalidate_source_and_schedule_rebuild(
        db, tenant_id="tenant-a", source_type="faq_corpus", source_id="faq",
        source_version="v1", reason="superseded", cache=cache, enqueue_rebuild=jobs.append,
    )
    job_id = jobs[0]["job_id"]
    claimed = claim_cache_rebuild(db, tenant_id="tenant-a", job_id=job_id)
    assert claimed["generation"] == 2
    assert read_current_cache(db, tenant_id="tenant-a", cache_key=old_key, cache=cache) is None

    cache.set(new_key, {"answer": "new"})
    completed = complete_cache_rebuild(
        db, tenant_id="tenant-a", job_id=job_id, storage_key=new_key, content_hash="sha256:new",
    )
    replay = complete_cache_rebuild(
        db, tenant_id="tenant-a", job_id=job_id, storage_key=new_key, content_hash="sha256:new",
    )
    assert completed["generation"] == 2
    assert replay["idempotent"] is True
    assert read_current_cache(db, tenant_id="tenant-a", cache_key=old_key, cache=cache) == {
        "answer": "new"
    }
    assert cache_lifecycle(db, tenant_id="tenant-a", cache_key=old_key)["status"] == "rebuilt"


def test_failed_or_degraded_rebuild_never_reenables_old_generation():
    db = _db()
    cache = SemanticCache()
    key = "cache:v2:faq:test"
    cache.set(key, {"answer": "old"})
    register_cache_dependency(
        db, tenant_id="tenant-a", cache_key=key,
        source_type="faq_corpus", source_id="faq", source_version="v1",
    )
    jobs = []
    invalidate_source_and_schedule_rebuild(
        db, tenant_id="tenant-a", source_type="faq_corpus", source_id="faq",
        source_version="v1", reason="superseded", cache=cache, enqueue_rebuild=jobs.append,
    )
    claim_cache_rebuild(db, tenant_id="tenant-a", job_id=jobs[0]["job_id"])
    failed = fail_cache_rebuild(
        db, tenant_id="tenant-a", job_id=jobs[0]["job_id"],
        error="model unavailable", retryable=True,
    )
    assert failed == {"job_id": jobs[0]["job_id"], "status": "degraded", "servable": False}
    assert read_current_cache(db, tenant_id="tenant-a", cache_key=key, cache=cache) is None


def test_operational_authorities_cannot_be_registered_as_cache_entries():
    db = _db()
    for namespace in ("atp", "demand_allocation", "payment_authorization"):
        try:
            register_cache_dependency(
                db, tenant_id="tenant-a", cache_key=f"cache:v2:{namespace}:key",
                source_type="inventory", source_id="sku-1", source_version="v1",
            )
        except ValueError as exc:
            assert str(exc) == "operational_authority_cache_prohibited"
        else:
            raise AssertionError(f"{namespace} must not be cacheable")


def test_same_key_and_source_version_are_tenant_isolated():
    db = _db()
    cache = SemanticCache()
    key = "cache:v2:faq:shared"
    cache.set(key, {"answer": "provider value"})
    for tenant in ("tenant-a", "tenant-b"):
        register_cache_dependency(
            db, tenant_id=tenant, cache_key=key,
            source_type="faq_corpus", source_id="faq", source_version="v1",
        )
    invalidate_source_and_schedule_rebuild(
        db, tenant_id="tenant-a", source_type="faq_corpus", source_id="faq",
        source_version="v1", reason="superseded", cache=cache,
    )
    assert cache_lifecycle(db, tenant_id="tenant-a", cache_key=key)["status"] == "rebuild_queued"
    assert cache_lifecycle(db, tenant_id="tenant-b", cache_key=key)["status"] == "fresh"


def test_stale_and_superseded_states_fail_closed():
    db = _db()
    cache = SemanticCache()
    key = "cache:v2:faq:status"
    cache.set(key, {"answer": "old"})
    register_cache_dependency(
        db, tenant_id="tenant-a", cache_key=key,
        source_type="faq_corpus", source_id="faq", source_version="v1",
    )
    assert mark_cache_stale(
        db, tenant_id="tenant-a", cache_key=key, reason="freshness_expired",
    )["changed"] is True
    assert read_current_cache(db, tenant_id="tenant-a", cache_key=key, cache=cache) is None
    assert supersede_cache_entry(
        db, tenant_id="tenant-a", cache_key=key, reason="new_contract", cache=cache,
    )["status"] == "superseded"
    assert cache_lifecycle(db, tenant_id="tenant-a", cache_key=key)["status"] == "superseded"


def test_worker_orchestration_publishes_handler_result_and_missing_handler_degrades():
    db = _db()
    cache = SemanticCache()
    key = "cache:v2:faq:worker"
    cache.set(key, {"answer": "old"})
    register_cache_dependency(
        db, tenant_id="tenant-a", cache_key=key,
        source_type="faq_corpus", source_id="faq", source_version="v1",
    )
    jobs = []
    invalidate_source_and_schedule_rebuild(
        db, tenant_id="tenant-a", source_type="faq_corpus", source_id="faq",
        source_version="v1", reason="superseded", cache=cache, enqueue_rebuild=jobs.append,
    )
    new_key = f"{key}:generation:2"
    cache.set(new_key, {"answer": "new"})
    register_rebuild_handler("faq", lambda _request: {
        "storage_key": new_key, "content_hash": "sha256:new",
    })
    try:
        assert execute_cache_rebuild(
            db, tenant_id="tenant-a", job_id=jobs[0]["job_id"],
        )["status"] == "rebuilt"
    finally:
        unregister_rebuild_handler("faq")

    second = "cache:v2:narration:worker"
    cache.set(second, {"answer": "old"})
    register_cache_dependency(
        db, tenant_id="tenant-a", cache_key=second,
        source_type="narration_source", source_id="case-1", source_version="v1",
    )
    more_jobs = []
    invalidate_source_and_schedule_rebuild(
        db, tenant_id="tenant-a", source_type="narration_source", source_id="case-1",
        source_version="v1", reason="superseded", cache=cache,
        enqueue_rebuild=more_jobs.append,
    )
    degraded = execute_cache_rebuild(
        db, tenant_id="tenant-a", job_id=more_jobs[0]["job_id"],
    )
    assert degraded["status"] == "degraded"
    assert read_current_cache(db, tenant_id="tenant-a", cache_key=second, cache=cache) is None


def test_durable_dispatch_is_tenant_scoped_and_does_not_redispatch_marked_jobs():
    db = _db()
    cache = SemanticCache()
    for tenant in ("tenant-a", "tenant-b"):
        key = f"cache:v2:faq:{tenant}"
        cache.set(key, {"tenant": tenant})
        register_cache_dependency(
            db, tenant_id=tenant, cache_key=key,
            source_type="faq_corpus", source_id="faq", source_version="v1",
        )
        invalidate_source_and_schedule_rebuild(
            db, tenant_id=tenant, source_type="faq_corpus", source_id="faq",
            source_version="v1", reason="superseded", cache=cache,
        )
    sent = []
    first = dispatch_queued_rebuilds(
        db, tenant_id="tenant-a", dispatch=lambda tenant, job: sent.append((tenant, job)),
    )
    replay = dispatch_queued_rebuilds(
        db, tenant_id="tenant-a", dispatch=lambda tenant, job: sent.append((tenant, job)),
    )
    assert first["examined"] == 1
    assert replay["examined"] == 0
    assert len(sent) == 1
    assert sent[0][0] == "tenant-a"


def test_operator_lifecycle_projection_is_tenant_scoped_and_honest_about_scope():
    db = _db()
    register_cache_dependency(
        db, tenant_id="tenant-a", cache_key="cache:v2:faq:one",
        source_type="faq_corpus", source_id="faq", source_version="v1",
    )
    register_cache_dependency(
        db, tenant_id="tenant-b", cache_key="cache:v2:faq:two",
        source_type="faq_corpus", source_id="faq", source_version="v1",
    )
    tenant_view = tenant_cache_lifecycle_projection(db, tenant_id="tenant-a")
    assert tenant_view["scope"] == "tenant_operator_summary"
    assert tenant_view["case_specific"] is False
    assert tenant_view["stale_content_served"] is False
    assert [row["cache_key"] for row in tenant_view["entries"]] == ["cache:v2:faq:one"]
    exact = tenant_cache_lifecycle_projection(
        db, tenant_id="tenant-a", cache_key="cache:v2:faq:one",
    )
    assert exact["scope"] == "exact_cache_key"
    assert exact["case_specific"] is True
    assert exact["entries"][0]["source_version"] is None
