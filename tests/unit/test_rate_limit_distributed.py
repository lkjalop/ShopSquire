from fastapi import FastAPI
from fastapi.testclient import TestClient

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
