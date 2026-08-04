from src.app.services.memory import MEMORY_CONTRACT_VERSION, Memory
from src.app.services.episodic_memory import Episode, EpisodicMemory, UserProfile


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
