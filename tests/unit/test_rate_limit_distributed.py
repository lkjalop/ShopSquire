from src.app.security import rate_limit as rl


def test_consume_fixed_window_fallback_store():
    store = {}
    key = "scope:ip:127.0.0.1"
    assert rl.consume_fixed_window_limit(key=key, limit=2, window_sec=60, fallback_store=store, now_ts=1000.0) is True
    assert rl.consume_fixed_window_limit(key=key, limit=2, window_sec=60, fallback_store=store, now_ts=1000.1) is True
    assert rl.consume_fixed_window_limit(key=key, limit=2, window_sec=60, fallback_store=store, now_ts=1000.2) is False


def test_concurrency_slot_fallback_store_acquire_and_release():
    store = {}
    key = "tenant:acme"
    assert rl.acquire_concurrency_slot(key=key, limit=1, ttl_sec=60, fallback_store=store) is True
    assert rl.acquire_concurrency_slot(key=key, limit=1, ttl_sec=60, fallback_store=store) is False
    rl.release_concurrency_slot(key=key, fallback_store=store)
    assert rl.acquire_concurrency_slot(key=key, limit=1, ttl_sec=60, fallback_store=store) is True
