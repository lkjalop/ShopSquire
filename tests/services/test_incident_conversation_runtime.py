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
