"""0.2 — DSR erasure must cover EVERY user-linked Redis key (was 3 of 13)."""
from __future__ import annotations

from src.app.services import user_data_inventory as udi
from src.app.services import memory as _memory


from tests.services.test_memory_scope_contract import _Redis


class _FakeRedis(_Redis):
    def __init__(self):
        super().__init__()
        self.store = self.data


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


def test_privacy_state_erasure_is_scoped_to_the_current_controller():
    from src.app.services.privacy_state_store import privacy_key
    from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id
    backend = _FakeRedis()
    uid = 'same-subject'
    keys = {}
    for tenant in ('controller-a', 'controller-b'):
        token = set_active_tenant_id(tenant)
        try:
            keys[tenant] = [privacy_key(uid, kind) for kind in ('consent', 'requests')]
            for key in keys[tenant]:
                backend.store[key] = '{"retention_opt_in":true}'
        finally:
            reset_active_tenant_id(token)
    token = set_active_tenant_id('controller-a')
    try:
        exported = udi.export_redis(backend, uid)
        assert set(exported) == {'privacy:consent', 'privacy:requests'}
        result = udi.erase_redis(backend, uid)
    finally:
        reset_active_tenant_id(token)
    assert result['complete'] is True
    assert all(key not in backend.store for key in keys['controller-a'])
    assert all(key in backend.store for key in keys['controller-b'])


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
