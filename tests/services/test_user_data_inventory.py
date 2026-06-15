"""0.2 — DSR erasure must cover EVERY user-linked Redis key (was 3 of 13)."""
from __future__ import annotations

from src.app.services import user_data_inventory as udi
from src.app.services import memory as _memory


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, k):
        return self.store.get(k)

    def delete(self, k):
        self.store.pop(k, None)


def _seed(uid: str) -> _FakeRedis:
    r = _FakeRedis()
    for key in udi.all_redis_keys(uid):
        r.store[key] = '{"x": 1}'
    return r


def test_inventory_covers_all_eight_memory_families():
    templates = udi.all_redis_key_templates()
    for k in (
        _memory.SUMMARY_KEY, _memory.KV_KEY, _memory.RETRIEVAL_KEY,
        _memory.AGENT_STEPS_KEY, _memory.STRUCTURED_STATE_KEY,
        _memory.PRODUCT_MEMORY_BANK_KEY, _memory.OBSERVATION_LOG_KEY,
        _memory.OBSERVATION_SUMMARY_KEY,
    ):
        assert k in templates


def test_erase_leaves_nothing_behind():
    uid = "u-123"
    r = _seed(uid)
    assert len(r.store) >= 13  # 8 memory + typed artifacts
    res = udi.erase_redis(r, uid)
    assert res["complete"] is True
    assert res["keys_failed"] == []
    # Every user-linked key is gone.
    assert r.store == {}


def test_export_returns_all_present_keys():
    uid = "u-9"
    r = _seed(uid)
    exported = udi.export_redis(r, uid)
    # one entry per seeded key, keyed by the short suffix
    assert len(exported) == len(udi.all_redis_keys(uid))
    assert "product_memory_bank" in exported
    assert "observation_log" in exported


def test_no_drift_keys_are_unique():
    templates = udi.all_redis_key_templates()
    assert len(templates) == len(set(templates))
