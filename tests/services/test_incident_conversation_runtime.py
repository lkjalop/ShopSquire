from src.app.services.incident_conversation_runtime import IncidentConversationRuntime


def test_runtime_tracks_multiple_staff_and_local_delivery(monkeypatch):
    runtime = IncidentConversationRuntime()
    monkeypatch.setattr(runtime, "_write_redis_presence", lambda *_args: None)
    monkeypatch.setattr(runtime, "_remove_redis_presence", lambda *_args: None)
    first = {"actor_id": "staff:alice", "display_name": "Alice"}
    second = {"actor_id": "staff:bob", "display_name": "Bob"}

    assert runtime.join("inc-1", first) is True
    assert runtime.join("inc-1", first) is False
    assert runtime.join("inc-1", second) is True
    assert [item["actor_id"] for item in runtime.active_staff("inc-1")] == ["staff:alice", "staff:bob"]

    queue = runtime.subscribe("inc-1")
    runtime.publish_local("inc-1", {"event_id": "evt-1"})
    assert queue.get_nowait() == {"event_id": "evt-1"}
    runtime.unsubscribe("inc-1", queue)
    assert "inc-1" not in runtime.subscribers

    assert runtime.leave("inc-1", first) is True
    assert runtime.leave("inc-1", first) is False


def test_runtime_distribution_status_never_claims_cross_worker_event_delivery(monkeypatch):
    runtime = IncidentConversationRuntime()
    monkeypatch.setattr("src.app.services.incident_conversation_runtime.get_redis", lambda: object())
    assert runtime.distribution_status == "redis_presence_local_events"


def test_publish_uses_broker_envelope_without_duplicating_local_delivery(monkeypatch):
    published = []

    class Broker:
        def publish(self, channel, payload):
            published.append((channel, payload))

    runtime = IncidentConversationRuntime(instance_id="worker-a")
    monkeypatch.setattr("src.app.services.incident_conversation_runtime.get_redis", lambda: Broker())
    queue = runtime.subscribe("inc-2")
    runtime.publish_local("inc-2", {"event_id": "evt-2"})
    assert queue.get_nowait()["event_id"] == "evt-2"
    assert queue.empty()
    assert published[0][0] == "shopsquire:incident_conversation"
    envelope = __import__("json").loads(published[0][1])
    assert envelope["origin"] == "worker-a"
    assert envelope["incident_id"] == "inc-2"


def test_presence_uses_atomic_hash_and_is_visible_to_another_worker(monkeypatch):
    class SharedRedis:
        def __init__(self):
            self.hashes = {}
            self.expiries = {}

        def hset(self, key, field, value):
            self.hashes.setdefault(key, {})[field] = value

        def hgetall(self, key):
            return dict(self.hashes.get(key, {}))

        def hdel(self, key, field):
            self.hashes.setdefault(key, {}).pop(field, None)

        def expire(self, key, seconds):
            self.expiries[key] = seconds

    redis = SharedRedis()
    monkeypatch.setattr("src.app.services.incident_conversation_runtime.get_redis", lambda: redis)
    first_worker = IncidentConversationRuntime(instance_id="worker-a")
    second_worker = IncidentConversationRuntime(instance_id="worker-b")

    first_worker.join("inc-shared", {"actor_id": "staff:alice", "display_name": "Alice"})
    second_worker.join("inc-shared", {"actor_id": "staff:bob", "display_name": "Bob"})

    assert [row["actor_id"] for row in first_worker.active_staff("inc-shared")] == ["staff:alice", "staff:bob"]
    assert redis.expiries["incident_chat_presence:inc-shared"] == 90
    second_worker.leave("inc-shared", {"actor_id": "staff:bob"})
    assert [row["actor_id"] for row in first_worker.active_staff("inc-shared")] == ["staff:alice"]
