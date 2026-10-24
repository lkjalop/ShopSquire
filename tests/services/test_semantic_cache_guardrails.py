import time
import pytest

from src.app.services.semantic_cache import SemanticCache


@pytest.mark.parametrize('failure', ['read_index', 'delete_value', 'delete_index'])
def test_erasure_reports_shared_backend_failure_and_preserves_retry_index(failure):
    from src.app.services.semantic_cache import CacheContract
    contract = CacheContract.resolve(tenant_id='cache-erasure', subject_id=failure,
        corpus_version='c', policy_version='p', model_version='m', evidence_cutoff='now')
    index = contract.erasure_index_key

    class Redis:
        failed = True
        data = {'value': 'PRIVATE'}
        members = {'value'}

        def smembers(self, key):
            if self.failed and failure == 'read_index': raise ConnectionError('offline')
            return self.members.copy()

        def delete(self, key):
            if self.failed and ((key == index and failure == 'delete_index') or
                                (key != index and failure == 'delete_value')):
                raise ConnectionError('offline')
            if key == index: self.members.clear()
            self.data.pop(key, None)

    redis = Redis()
    cache = SemanticCache(redis_client=redis)
    with pytest.raises(RuntimeError, match='cache_erasure_incomplete'):
        cache.erase_scope(contract)
    assert redis.members == {'value'}
    redis.failed = False
    assert cache.erase_scope(contract) == 1
    assert redis.data == {} and redis.members == set()


def test_semantic_cache_local_ttl_expires():
    c = SemanticCache(redis_url=None, default_ttl=1)
    c.set("k1", {"v": 1}, ex=1)
    assert c.get("k1") == {"v": 1}
    time.sleep(1.2)
    assert c.get("k1") is None


def test_semantic_cache_safe_quarantine_blocks_read():
    c = SemanticCache(redis_url=None, default_ttl=60)
    c.set_safe("k2", {"answer": "ok"}, source_id="faq", trust_score=0.8, ex=30)
    assert c.get_safe("k2", min_trust=0.5) == {"answer": "ok"}
    c.quarantine("k2", reason="poison_detected")
    assert c.get_safe("k2", min_trust=0.1) is None


def test_semantic_cache_safe_min_trust_enforced():
    c = SemanticCache(redis_url=None, default_ttl=60)
    c.set_safe("k3", {"answer": "low"}, source_id="unknown", trust_score=0.2, ex=30)
    assert c.get_safe("k3", min_trust=0.3) is None
    assert c.get_safe("k3", min_trust=0.1) == {"answer": "low"}


def test_versioned_local_eviction_also_bounds_privacy_index_memory():
    from dataclasses import replace
    from src.app.services.semantic_cache import CacheContract
    contract = CacheContract.resolve(tenant_id='owned', subject_id='0', corpus_version='c',
        policy_version='p', model_version='m', evidence_cutoff='now')
    cache = SemanticCache(maxsize=2)
    for n in range(500):
        cache.set_versioned(namespace='test', request=n, contract=replace(contract, subject_id=str(n)),
            value='private', source_id='owned', trust_score=1)
    assert len(cache._local) <= 2
    assert len(cache._local_scope_index) <= 2
    assert len(cache._local_key_scope) <= 2
    assert cache.erase_scope(contract) == 0
