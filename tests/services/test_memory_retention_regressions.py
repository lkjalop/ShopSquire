"""Privacy failures must not be hidden by a passing recall-only test."""
import pytest

from src.app.services.memory import Memory
from tests.services.test_memory_scope_contract import _Redis


def isolated_memory(backend=None):
    memory = Memory(backend, tenant_id='retention-regression')
    memory._LOCAL_STORE = {}
    memory._LOCAL_INDEX = {}
    return memory


def test_failed_index_registration_never_leaves_an_unerasable_shared_value():
    class BrokenIndex(_Redis):
        def sadd(self, *args):
            raise ConnectionError('index write failed')

    backend = BrokenIndex()
    writer = isolated_memory(backend)
    writer.set_kv('buyer', {'private': 'ERASURE_CANARY'})
    # A replacement worker has no access to the first worker's fallback index.
    replacement = isolated_memory(backend)
    replacement.erase_subject('buyer')
    assert replacement.get_kv('buyer') == {}
    assert not backend.data


def test_expired_subjects_are_reclaimed_without_reading_every_subject(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('src.app.services.memory.time.time', lambda: clock[0])
    memory = isolated_memory()
    for n in range(200):
        memory.set_kv(str(n), {'quantity': n}, ttl_seconds=1)
    clock[0] += 2
    memory.set_kv('active', {'quantity': 40})
    assert len(memory._LOCAL_STORE) == 1
    assert len(memory._LOCAL_INDEX) == 1
    assert memory.get_kv('active') == {'quantity': 40}


def test_local_retention_has_a_capacity_limit_and_keeps_recent_conversation(monkeypatch):
    monkeypatch.setenv('MEMORY_LOCAL_MAX_KEYS', '16')
    memory = isolated_memory()
    for n in range(100):
        memory.set_kv(str(n), {'quantity': n})
    assert len(memory._LOCAL_STORE) <= 16
    assert len(memory._LOCAL_INDEX) <= 16
    assert memory.get_kv('99') == {'quantity': 99}
    assert memory.get_kv('0') == {}


def test_local_retention_bounds_payload_bytes(monkeypatch):
    monkeypatch.setenv('MEMORY_LOCAL_MAX_BYTES', '2048')
    memory = isolated_memory()
    for n in range(30):
        memory.set_kv(str(n), {'message': 'x' * 700})
    assert sum(len(row['value'].encode()) for row in memory._LOCAL_STORE.values()) <= 2048
    assert memory.get_kv('29')['message'] == 'x' * 700


def test_scripted_erasure_failure_cannot_restore_the_local_private_copy():
    class Scripted(_Redis):
        def eval(self, script, *args):
            raise ConnectionError('script transport failed')
    backend = Scripted()
    memory = isolated_memory(backend)
    # Seed a shared value using the compatibility path, then fail only erasure.
    backend.eval = None
    memory.set_kv('buyer', {'private': 'FAILED_ERASE_CANARY'})
    del backend.eval
    with pytest.raises(RuntimeError, match='memory_erasure_incomplete'):
        memory.erase_subject('buyer')
    assert memory.get_kv('buyer') == {}
