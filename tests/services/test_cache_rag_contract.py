from src.app.services.agentic_rag_pipeline import run_agentic_rag_pipeline
from src.app.services.semantic_cache import (
    CACHE_CONTRACT_VERSION,
    CacheContract,
    SemanticCache,
    stable_citation_id,
)


def _contract(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "corpus_version": "corpus-1",
        "policy_version": "policy-1",
        "model_version": "model-1",
        "evidence_cutoff": "2026-07-30T00:00:00Z",
        "subject_id": "buyer-1",
        "session_epoch": "session-1",
    }
    values.update(overrides)
    return CacheContract.resolve(**values)


def test_versioned_cache_never_reuses_across_authority_boundaries():
    cache = SemanticCache(redis_url=None)
    request = {"query": "return policy"}
    original = _contract()
    cache.set_versioned(
        namespace="rag",
        request=request,
        contract=original,
        value={"answer": "14 days"},
        source_id="policy",
        trust_score=0.9,
    )

    assert cache.get_versioned(
        namespace="rag", request=request, contract=original
    ) == {"answer": "14 days"}
    for changed in (
        _contract(tenant_id="tenant-b"),
        _contract(session_epoch="session-2"),
        _contract(corpus_version="corpus-2"),
        _contract(policy_version="policy-2"),
        _contract(model_version="model-2"),
        _contract(evidence_cutoff="2026-07-31T00:00:00Z"),
    ):
        assert cache.get_versioned(
            namespace="rag", request=request, contract=changed
        ) is None


def test_versioned_cache_subject_erasure_removes_all_versions():
    cache = SemanticCache(redis_url=None)
    request = {"query": "availability"}
    for corpus in ("one", "two"):
        cache.set_versioned(
            namespace="rag",
            request=request,
            contract=_contract(corpus_version=corpus),
            value={"corpus": corpus},
            source_id="inventory",
            trust_score=0.9,
        )

    assert cache.erase_scope(_contract()) == 2
    assert cache.get_versioned(
        namespace="rag", request=request, contract=_contract(corpus_version="one")
    ) is None


def test_citation_identity_is_stable_and_revision_sensitive():
    args = {
        "source_id": "faq_bank",
        "document_id": "returns",
        "revision": "2026-07",
        "locator": "paragraph-2",
        "content_hash": "abc",
    }
    first = stable_citation_id(**args)
    assert first == stable_citation_id(**args)
    assert first.startswith("cite:v1:")
    assert first != stable_citation_id(**{**args, "revision": "2026-08"})


def test_agentic_rag_exposes_version_contract_and_stable_citations():
    kwargs = {
        "question": "How do I do a warranty return for broken screen?",
        "tenant_id": "tenant-a",
        "subject_id": "buyer-1",
        "session_epoch": "session-1",
        "evidence_cutoff": "bundled",
    }
    first = run_agentic_rag_pipeline(trace_id="rag-contract-1", **kwargs)
    second = run_agentic_rag_pipeline(trace_id="rag-contract-2", **kwargs)

    assert first["contract_version"] == CACHE_CONTRACT_VERSION
    assert first["cache_contract"]["evidence_cutoff"] == "bundled"
    assert first["citations"] == second["citations"]
    assert all(item.startswith("cite:v1:") for item in first["citations"])
    assert second["cache_hit"] is True


def test_agentic_rag_exposes_exact_cache_dependency_to_temporal_composition():
    dependencies = []
    result = run_agentic_rag_pipeline(
        question="What is the warranty process?",
        tenant_id="tenant-temporal",
        subject_id="buyer-temporal",
        session_epoch="epoch-1",
        corpus_version="faq-temporal-rev-7",
        evidence_cutoff="2026-08-03T00:00:00Z",
        cache_dependency_recorder=dependencies.append,
    )

    assert result["cache_dependency_registered"] is True
    assert dependencies[0]["tenant_id"] == "tenant-temporal"
    assert dependencies[0]["cache_key"] == result["cache_key"]
    assert dependencies[0]["source_type"] == "faq_corpus"
    assert dependencies[0]["source_id"] == "faq_bank"
    assert dependencies[0]["source_version"] == "faq-temporal-rev-7"
    assert dependencies[0]["namespace"] == "agentic_rag_retrieval"
    assert dependencies[0]["subject_type"] == "case"
    assert dependencies[0]["subject_id"] == "buyer-temporal"
    assert dependencies[0]["session_epoch"] == "epoch-1"
    assert dependencies[0]["rebuild_payload"]["contract"]["subject_id"] == "buyer-temporal"
    assert dependencies[0]["rebuild_payload"]["request"]["intent"]


def test_unregistered_cache_entry_is_evicted_and_reported_as_degraded():
    result = run_agentic_rag_pipeline(
        question="What is the return process?",
        tenant_id="tenant-temporal-failure",
        corpus_version="faq-temporal-failure-rev-1",
        evidence_cutoff="2026-08-03T00:00:00Z",
        cache_dependency_recorder=lambda _item: (_ for _ in ()).throw(
            RuntimeError("registry unavailable")
        ),
    )

    assert result["cache_dependency_registered"] is False
    assert result["cache_temporal_status"] == "degraded_dependency_unavailable"
    assert result["cache_hit"] is False


def test_durable_lifecycle_blocks_stale_provider_value_before_retrieval():
    kwargs = {
        "question": "How long do warranty returns take?",
        "tenant_id": "tenant-lifecycle-guard",
        "corpus_version": "faq-lifecycle-guard-v1",
        "evidence_cutoff": "2026-08-03T05:00:00Z",
        "cache_dependency_recorder": lambda _item: None,
    }
    first = run_agentic_rag_pipeline(
        **kwargs, cache_lifecycle_resolver=lambda _item: {
            "status": "unregistered", "servable": False,
        },
    )
    second = run_agentic_rag_pipeline(
        **kwargs, cache_lifecycle_resolver=lambda _item: {
            "status": "invalidated", "servable": False,
        },
    )

    assert first["cache_hit"] is False
    assert second["cache_hit"] is False
    assert second["cache_temporal_read_status"] == "invalidated"
