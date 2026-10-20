"""Concurrent signed deliveries must acquire one shared replay reservation."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import os
from threading import Barrier, Lock
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.app.security import webhook_security as security
from tests.webhooks.test_webhook_signature import _clear_webhook_replay_state


class ConcurrentRedis:
    def __init__(self):
        self.values = {}
        self.lock = Lock()
        self.readers = Barrier(8)

    def get(self, key):
        with self.lock:
            value = self.values.get(key)
        # Model eight independent API workers reading before any writes.
        self.readers.wait(timeout=5)
        return value

    def setex(self, key, ttl, value):
        with self.lock:
            self.values[key] = value
        return True

    def set(self, key, value, *, nx, ex):
        assert nx is True and ex > 0
        with self.lock:
            if key in self.values:
                return None
            self.values[key] = value
            return True


def make_delivery(monkeypatch, backend, vendor):
    monkeypatch.setattr(security, "_LOCAL_REPLAY_CACHE", {})
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("WEBHOOK_SECRET", "owned-test-secret")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "owned-test-secret")
    monkeypatch.setattr(security, "get_redis", lambda: backend)
    monkeypatch.setattr(security, "log_agent_security_event", lambda **kwargs: None)
    app = FastAPI()
    app.add_middleware(security.WebhookSecurityMiddleware)
    path = "/api/v1/webhooks/github" if vendor else "/api/v1/admin/connectors/test"
    effects = []

    @app.post(path)
    async def receive():
        effects.append("accepted")
        return {"received": True}

    payload = b'{"id":"owned-concurrent-delivery"}'
    timestamp = str(int(time.time()))
    signed = payload if vendor else timestamp.encode() + b"." + payload
    signature = hmac.new(b"owned-test-secret", signed, hashlib.sha256).hexdigest()
    headers = {"content-type": "application/json"}
    if vendor:
        headers["x-hub-signature-256"] = "sha256=" + signature
    else:
        headers.update({"x-webhook-signature": signature, "x-webhook-timestamp": timestamp})

    def deliver():
        with TestClient(app) as client:
            return client.post(path, content=payload, headers=headers).status_code

    return deliver, effects


@pytest.mark.parametrize("vendor", [False, True], ids=["generic", "github"])
def test_concurrent_workers_accept_exactly_one_delivery(monkeypatch, vendor):
    deliver, effects = make_delivery(monkeypatch, ConcurrentRedis(), vendor)
    with ThreadPoolExecutor(max_workers=8) as workers:
        statuses = list(workers.map(lambda _: deliver(), range(8)))
    assert sorted(statuses) == [200] + [409] * 7
    assert effects == ["accepted"]


@pytest.mark.parametrize("vendor", [False, True], ids=["generic", "github"])
def test_replay_backend_outage_blocks_handler(monkeypatch, vendor):
    class UnavailableRedis:
        def get(self, *args):
            raise ConnectionError("owned backend outage")

        def set(self, *args, **kwargs):
            raise ConnectionError("owned backend outage")

    deliver, effects = make_delivery(monkeypatch, UnavailableRedis(), vendor)
    assert deliver() == 503
    assert effects == []


@pytest.mark.parametrize("environment", [None, "", "production"])
def test_production_does_not_use_process_local_replay(monkeypatch, environment):
    class DummyRedis:
        pass

    deliver, effects = make_delivery(monkeypatch, DummyRedis(), False)
    if environment is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", environment)
    assert deliver() == 503
    assert effects == []


@pytest.mark.parametrize("vendor", [False, True], ids=["generic", "github"])
def test_real_redis_concurrent_delivery(monkeypatch, vendor):
    if os.getenv("RUN_WEBHOOK_SECURITY_TESTS") != "1":
        pytest.skip("requires the explicit owned Redis security profile")
    backend = security.get_redis()
    assert backend.__class__.__name__ != "DummyRedis", "required Redis profile is unavailable"
    deliver, effects = make_delivery(monkeypatch, backend, vendor)
    with ThreadPoolExecutor(max_workers=8) as workers:
        statuses = list(workers.map(lambda _: deliver(), range(8)))
    assert sorted(statuses) == [200] + [409] * 7
    assert effects == ["accepted"]


def test_explicit_development_fallback_is_atomic_and_expires(monkeypatch):
    class DummyRedis:
        pass

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(security, "get_redis", lambda: DummyRedis())
    monkeypatch.setattr(security, "_LOCAL_REPLAY_CACHE", {})
    monkeypatch.setattr(security.time, "monotonic", lambda: 100)
    with ThreadPoolExecutor(max_workers=8) as workers:
        seen = list(workers.map(lambda _: security._replay_seen("owned-key", 5), range(8)))
    assert seen.count(False) == 1
    assert seen.count(True) == 7
    monkeypatch.setattr(security.time, "monotonic", lambda: 105)
    assert security._replay_seen("owned-key", 5) is False
    assert security._LOCAL_REPLAY_CACHE == {"owned-key": 110}


def test_full_local_store_does_not_evict_live_replay_claims(monkeypatch):
    monkeypatch.setattr(security.time, "monotonic", lambda: 100)
    monkeypatch.setattr(security, "_LOCAL_REPLAY_CACHE", {str(i): 101 for i in range(10000)})
    with pytest.raises(security.HTTPException) as blocked:
        security._replay_seen_local("new-key", 10)
    assert blocked.value.status_code == 503
    assert "new-key" not in security._LOCAL_REPLAY_CACHE
    assert security._replay_seen_local("0", 10) is True


def test_unrecognized_claim_acknowledgment_blocks_handler(monkeypatch):
    class InvalidRedis:
        def set(self, *args, **kwargs):
            return {"unknown": "response"}

    deliver, effects = make_delivery(monkeypatch, InvalidRedis(), False)
    assert deliver() == 503
    assert effects == []


@pytest.mark.parametrize("vendor", [False, True], ids=["generic", "github"])
def test_replay_audit_failure_does_not_allow_handler(monkeypatch, vendor):
    class AlreadyClaimedRedis:
        def set(self, *args, **kwargs):
            return None

    deliver, effects = make_delivery(monkeypatch, AlreadyClaimedRedis(), vendor)

    def failed_audit(**kwargs):
        raise RuntimeError("owned audit failure")

    monkeypatch.setattr(security, "log_agent_security_event", failed_audit)
    assert deliver() == 503
    assert effects == []
