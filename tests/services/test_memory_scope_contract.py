from src.app.services.memory import MEMORY_CONTRACT_VERSION, Memory
from src.app.services.episodic_memory import Episode, EpisodicMemory, UserProfile
import pytest


class _Redis:
    def __init__(self):
        self.data = {}
        self.sets = {}

    def setex(self, key, _ttl, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)
            self.sets.pop(key, None)

    def expire(self, _key, _ttl):
        return True

    def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(values)

    def srem(self, key, *values):
        self.sets.setdefault(key, set()).difference_update(values)

    def smembers(self, key):
        return self.sets.get(key, set())


def test_other_worker_erasure_cannot_resurrect_local_conversation_copy():
    redis=_Redis()
    writer=Memory(redis,tenant_id='worker-erasure')
    eraser=Memory(redis,tenant_id='worker-erasure')
    # Model distinct process-local stores rather than accidentally sharing the
    # class cache and making a distributed erasure test pass locally.
    writer._LOCAL_STORE={};writer._LOCAL_INDEX={}
    eraser._LOCAL_STORE={};eraser._LOCAL_INDEX={}
    writer.set_kv('buyer',{'private':'CONVERSATION_CANARY'})
    eraser.erase_subject('buyer')
    assert writer.get_kv('buyer')=={}


def test_shared_conversation_read_abstains_during_partition():
    class Partition(_Redis):
        offline=False
        def get(self,key):
            if self.offline:raise ConnectionError('partition')
            return super().get(key)
    redis=Partition();memory=Memory(redis,tenant_id='partitioned-memory')
    memory.set_kv('buyer',{'private':'CONVERSATION_CANARY'})
    redis.offline=True
    assert memory.get_kv('buyer')=={}
    redis.offline=False
    assert memory.get_kv('buyer')=={'private':'CONVERSATION_CANARY'}


def test_failed_backend_write_cannot_resurrect_old_context_on_recovery():
    class FlakyRedis(_Redis):
        failed=False
        def setex(self,*args):
            if self.failed:raise ConnectionError('injected write failure')
            super().setex(*args)
    redis=FlakyRedis();memory=Memory(redis)
    scope=dict(tenant_id='outage-test',session_epoch='outage-epoch')
    memory.set_kv('buyer',{'quantity':30},**scope)
    redis.failed=True
    memory.set_kv('buyer',{'quantity':40},**scope)
    redis.failed=False
    assert Memory(redis).get_kv('buyer',**scope)=={'quantity':40}
    assert Memory(redis).get_kv('other',**scope)=={}


@pytest.mark.parametrize('operation',['session','clarification','subject'])
def test_failed_delete_is_reported_and_old_memory_cannot_reappear_locally(operation):
    class FlakyRedis(_Redis):
        failed=False
        def delete(self,*keys):
            if self.failed:raise ConnectionError('injected delete failure')
            super().delete(*keys)
    redis=FlakyRedis();memory=Memory(redis,tenant_id='delete-'+operation)
    memory.set_pending_clarification('buyer',{'budget':1000})
    redis.failed=True
    action={'session':lambda:memory.clear_session('buyer'),
            'clarification':lambda:memory.clear_pending_clarification('buyer'),
            'subject':lambda:memory.erase_subject('buyer')}[operation]
    with pytest.raises(RuntimeError,match='memory_erasure_incomplete'):action()
    redis.failed=False
    assert memory.get_pending_clarification('buyer')=={}
    action()
    assert not redis.data


def test_memory_isolated_by_tenant_subject_and_session_epoch():
    redis = _Redis()
    memory = Memory(redis)
    memory.set_kv(
        "buyer",
        {"budget": 1000},
        tenant_id="tenant-a",
        subject_id="buyer",
        session_epoch="session-1",
    )

    assert memory.get_kv(
        "buyer", tenant_id="tenant-a", subject_id="buyer", session_epoch="session-1"
    ) == {"budget": 1000}
    assert memory.get_kv(
        "buyer", tenant_id="tenant-b", subject_id="buyer", session_epoch="session-1"
    ) == {}
    assert memory.get_kv(
        "buyer", tenant_id="tenant-a", subject_id="buyer", session_epoch="session-2"
    ) == {}
    assert memory.get_kv(
        "other", tenant_id="tenant-a", subject_id="other", session_epoch="session-1"
    ) == {}
    assert all("tenant-a" not in key and "buyer" not in key for key in redis.data)


def test_subject_erasure_removes_every_epoch_but_not_another_tenant():
    redis = _Redis()
    memory = Memory(redis)
    for epoch in ("one", "two"):
        memory.set_summary(
            "buyer",
            {"epoch": epoch},
            tenant_id="tenant-a",
            subject_id="buyer",
            session_epoch=epoch,
        )
    memory.set_summary(
        "buyer",
        {"tenant": "b"},
        tenant_id="tenant-b",
        subject_id="buyer",
        session_epoch="one",
    )

    result = memory.erase_subject("buyer", tenant_id="tenant-a")

    assert result["contract_version"] == MEMORY_CONTRACT_VERSION
    # The process-local continuity cache can also contain an older epoch from
    # another Memory instance; erasure intentionally removes it too.
    assert result["erased_keys"] >= 2
    assert memory.get_context(
        "buyer", tenant_id="tenant-a", subject_id="buyer", session_epoch="one"
    )["summary"] is None
    assert memory.get_context(
        "buyer", tenant_id="tenant-b", subject_id="buyer", session_epoch="one"
    )["summary"] == {"tenant": "b"}


def test_episdodic_and_profile_memory_use_scoped_indexed_keys():
    redis = _Redis()
    memory = Memory(
        redis,
        tenant_id="tenant-a",
        subject_id="buyer",
        session_epoch="session-7",
    )
    episodic = EpisodicMemory(memory)
    episodic.append_episode(
        "buyer", Episode(turn_index=1, query="need a laptop", response_summary="shortlist")
    )
    episodic.save_user_profile(UserProfile(user_id="buyer", preferred_brands=["Framework"]))

    assert episodic.get_episodes("buyer")[0]["turn_index"] == 1
    assert episodic.get_user_profile("buyer").preferred_brands == ["Framework"]
    indexed = set().union(*redis.sets.values())
    assert any(key.endswith(":episodic_episodes") for key in indexed)
    assert any(key.endswith(":episodic_profile") for key in indexed)
    assert all("need a laptop" not in key for key in redis.data)


def test_clear_session_does_not_clear_other_epoch():
    redis = _Redis()
    memory = Memory(redis)
    for epoch in ("one", "two"):
        memory.set_pending_clarification(
            "buyer",
            {"epoch": epoch},
            tenant_id="tenant-a",
            session_epoch=epoch,
        )

    memory.clear_session("buyer", tenant_id="tenant-a", session_epoch="one")

    assert memory.get_pending_clarification(
        "buyer", tenant_id="tenant-a", session_epoch="one"
    ) == {}
    assert memory.get_pending_clarification(
        "buyer", tenant_id="tenant-a", session_epoch="two"
    ) == {"epoch": "two"}
