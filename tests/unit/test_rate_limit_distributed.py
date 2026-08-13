from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.security import rate_limit as rl


def test_consume_fixed_window_fallback_store(monkeypatch):
    monkeypatch.setattr(rl, "_redis_client", lambda: None)
    store = {}
    key = "scope:ip:127.0.0.1"
    assert rl.consume_fixed_window_limit(key=key, limit=2, window_sec=60, fallback_store=store, now_ts=1000.0) is True
    assert rl.consume_fixed_window_limit(key=key, limit=2, window_sec=60, fallback_store=store, now_ts=1000.1) is True
    assert rl.consume_fixed_window_limit(key=key, limit=2, window_sec=60, fallback_store=store, now_ts=1000.2) is False


def test_concurrency_slot_fallback_store_acquire_and_release(monkeypatch):
    monkeypatch.setattr(rl, "_redis_client", lambda: None)
    store = {}
    key = "tenant:acme"
    assert rl.acquire_concurrency_slot(key=key, limit=1, ttl_sec=60, fallback_store=store) is True
    assert rl.acquire_concurrency_slot(key=key, limit=1, ttl_sec=60, fallback_store=store) is False
    rl.release_concurrency_slot(key=key, fallback_store=store)
    assert rl.acquire_concurrency_slot(key=key, limit=1, ttl_sec=60, fallback_store=store) is True


def test_middleware_limit_is_a_429_response_not_an_asgi_500(monkeypatch):
    monkeypatch.setattr(rl, "_redis_client", lambda: None)
    rl._STATE.clear()
    app = FastAPI()
    app.add_middleware(rl.RateLimitMiddleware, per_min_key=1, per_min_ip=0)

    @app.get("/probe")
    def probe():
        return {"ok": True}

    client = TestClient(app)
    headers = {"x-api-key": "bounded-test-key"}
    assert client.get("/probe", headers=headers).status_code == 200
    response = client.get("/probe", headers=headers)
    assert response.status_code == 429
    assert response.json()["detail"].startswith("key_rate_limit_exceeded")


def test_cors_preflight_does_not_consume_or_trip_rate_limit(monkeypatch):
    monkeypatch.setattr(rl, "_redis_client", lambda: None)
    rl._STATE.clear()
    app = FastAPI()
    app.add_middleware(rl.RateLimitMiddleware, per_min_key=1, per_min_ip=1)

    @app.get("/resource")
    def resource():
        return {"ok": True}

    client = TestClient(app)
    for _ in range(3):
        response = client.options(
            "/resource",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code != 429

    assert client.get("/resource").status_code == 200


def test_redis_socket_timeout_uses_bounded_local_fallback(monkeypatch):
    from redis.exceptions import TimeoutError as RedisTimeoutError

    class TimedOutRedis:
        def incrby(self, *_args, **_kwargs):
            raise RedisTimeoutError("bounded test timeout")

    store = {}
    monkeypatch.setattr(rl, "_redis_client", lambda: TimedOutRedis())

    assert rl.consume_fixed_window_limit(
        key="timeout-scope", limit=1, window_sec=60, fallback_store=store, now_ts=1000.0
    ) is True
    assert rl.consume_fixed_window_limit(
        key="timeout-scope", limit=1, window_sec=60, fallback_store=store, now_ts=1000.1
    ) is False
