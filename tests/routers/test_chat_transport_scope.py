from src.app.routers.chat import _chat_idempotency_cache_key


def test_chat_idempotency_key_is_stable_within_one_conversation():
    first = _chat_idempotency_cache_key(
        tenant_id="tenant-a", uid="buyer-a", session_id="session-a",
        idempotency_key="turn-1",
    )
    retry = _chat_idempotency_cache_key(
        tenant_id="tenant-a", uid="buyer-a", session_id="session-a",
        idempotency_key="turn-1",
    )
    assert first == retry
    assert first.endswith(":turn-1")
    assert "buyer-a" not in first


def test_chat_idempotency_key_cannot_replay_across_users_or_tenants():
    baseline = _chat_idempotency_cache_key(
        tenant_id="tenant-a", uid="buyer-a", session_id="session-a",
        idempotency_key="turn-1",
    )
    assert baseline != _chat_idempotency_cache_key(
        tenant_id="tenant-a", uid="buyer-b", session_id="session-a",
        idempotency_key="turn-1",
    )
    assert baseline != _chat_idempotency_cache_key(
        tenant_id="tenant-b", uid="buyer-a", session_id="session-a",
        idempotency_key="turn-1",
    )
    assert baseline != _chat_idempotency_cache_key(
        tenant_id="tenant-a", uid="buyer-a", session_id="session-b",
        idempotency_key="turn-1",
    )
