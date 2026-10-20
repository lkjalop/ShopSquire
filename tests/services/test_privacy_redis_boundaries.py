"""Privacy operations cannot borrow legacy controller data or hide storage failure."""
import json

import pytest
from fastapi import HTTPException

from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id
from src.app.services import memory, user_data_inventory as inventory
from tests.services.test_memory_scope_contract import _Redis
from tests.services.test_privacy_decision_subject import decision_store  # noqa: F401

_REAL_EXPORT = inventory.export_redis


def seeded():
    backend = _Redis()
    uid = 'shared-subject'
    legacy = [template.format(uid=uid) for template in inventory.all_redis_key_templates()]
    for key in legacy:
        backend.setex(key, 600, json.dumps({'private': 'DEFAULT_CONTROLLER_CANARY'}))
    owned = memory.Memory(backend, tenant_id='controller-a')
    owned.set_kv(uid, {'quantity': 40})
    return backend, uid, legacy, owned


def test_named_controller_export_excludes_uid_only_legacy_keys():
    backend, uid, _, owned = seeded()
    token = set_active_tenant_id('controller-a')
    try:
        result = inventory.export_redis(backend, uid)
    finally:
        reset_active_tenant_id(token)
    assert 'DEFAULT_CONTROLLER_CANARY' not in json.dumps(result)
    key = owned.scoped_key('kv_state', uid)
    assert result['v2:kv_state:' + key]['value']['quantity'] == 40


def test_named_controller_erasure_preserves_uid_only_legacy_keys():
    backend, uid, legacy, owned = seeded()
    token = set_active_tenant_id('controller-a')
    try:
        result = inventory.erase_redis(backend, uid)
    finally:
        reset_active_tenant_id(token)
    assert result['complete'] is True
    assert all(backend.get(key) is not None for key in legacy)
    assert owned.get_kv(uid) == {}


@pytest.mark.parametrize('failure', ['get', 'index'])
def test_export_storage_failure_cannot_look_like_an_empty_success(failure):
    class Broken(_Redis):
        def get(self, key):
            if failure == 'get':
                raise ConnectionError('Owned read failure')
            return super().get(key)

        def smembers(self, key):
            if failure == 'index':
                raise ConnectionError('Owned index failure')
            return super().smembers(key)

    with pytest.raises(RuntimeError, match='privacy_memory_export_incomplete'):
        inventory.export_redis(Broken(), 'outage-subject')


def test_export_of_unacknowledged_local_adapter_is_not_shared_memory_evidence():
    class LocalOnly(_Redis):
        is_shared_backend = False

    with pytest.raises(RuntimeError, match='privacy_memory_export_incomplete'):
        inventory.export_redis(LocalOnly(), 'local-only-subject')


def test_indexed_value_read_failure_cannot_drop_one_session_silently():
    class BrokenValue(_Redis):
        rejected_key = None

        def get(self, key):
            if key == self.rejected_key:
                raise ConnectionError('Owned session read failure')
            return super().get(key)

    backend = BrokenValue()
    store = memory.Memory(backend)
    store.set_kv('value-outage', {'quantity': 40})
    backend.rejected_key = store.scoped_key('kv_state', 'value-outage')
    with pytest.raises(RuntimeError, match='privacy_memory_export_incomplete'):
        inventory.export_redis(backend, 'value-outage')


def test_export_endpoint_reports_storage_failure_as_retryable_unavailability(decision_store, monkeypatch):
    from src.app.routers import privacy

    class Unavailable(_Redis):
        def get(self, key):
            raise ConnectionError('private-backend-detail')

    monkeypatch.setattr(inventory, 'export_redis', _REAL_EXPORT)
    with pytest.raises(HTTPException) as failure:
        privacy.export_user_data('export-subject', Unavailable(), False, 'owner')
    assert failure.value.status_code == 503
    assert 'private-backend-detail' not in str(failure.value.detail)
