import time

from src.app.services.semantic_cache import SemanticCache


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

