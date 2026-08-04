import pytest

from src.app.services.agentic_rag_pipeline import PlanOutput
from src.app.services.semantic_cache import CacheContract, SemanticCache
from src.app.services.temporal_cache_producers import rebuild_agentic_rag_retrieval


class _Redis:
    def __init__(self):
        self.values = {}
        self.sets = {}

    def set(self, name, value, ex):
        self.values[name] = value

    def get(self, key):
        return self.values.get(key)

    def sadd(self, key, value):
        self.sets.setdefault(key, set()).add(value)

    def expire(self, key, seconds):
        return True


def _job():
    contract = CacheContract.resolve(
        tenant_id="tenant-a",
        corpus_version="faq-bank-test-rev",
        policy_version="policy-v1",
        model_version="model-v1",
        evidence_cutoff="2026-08-03T00:00:00Z",
        subject_id="case-42",
        session_epoch="epoch-7",
    )
    request = PlanOutput(queries=["return policy"], intent="returns_warranty").model_dump()
    return {
        "tenant_id": "tenant-a",
        "source_version": contract.corpus_version,
        "cache_key": contract.cache_key("agentic_rag_retrieval", request),
        "rebuild_payload": {
            "schema_version": "shopsquire.cache-rebuild.v1",
            "namespace": "agentic_rag_retrieval",
            "request": request,
            "contract": contract.__dict__,
        },
    }


def test_real_rag_producer_publishes_and_verifies_exact_generation():
    cache = SemanticCache(redis_client=_Redis())
    job = _job()

    result = rebuild_agentic_rag_retrieval(job, cache=cache)

    assert result["storage_key"] == job["cache_key"]
    assert result["published"] is True
    assert len(result["content_hash"]) == 64


def test_real_rag_producer_refuses_process_local_false_publication():
    with pytest.raises(RuntimeError, match="shared_cache_backend_required"):
        rebuild_agentic_rag_retrieval(_job(), cache=SemanticCache())
