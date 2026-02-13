from fastapi.testclient import TestClient

from tests.utils import default_headers

from src.app.main import create_app
from src.app.deps import get_redis
from src.app.services.memory import Memory


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, _ttl, value):
        self.store[key] = value


def test_memory_isolation_by_uid():
    fake = FakeRedis()
    mem = Memory(fake)
    mem.set_summary("u1", {"utterances": ["hi"], "summary_text": "hi"})
    mem.set_kv("u1", {"draft_cart_id": "d1"})
    ctx1 = mem.get_context("u1")
    ctx2 = mem.get_context("u2")
    assert ctx1.get("summary")
    assert ctx1.get("kv")
    assert ctx2.get("summary") is None
    assert ctx2.get("kv") is None


def test_session_memory_update_endpoint():
    fake = FakeRedis()
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: fake
    client = TestClient(app, headers=default_headers())
    try:
        r = client.post("/api/v1/session/user-1/memory/update", params={"utterance": "Need a 16GB laptop", "retrieval_ranks": ["p1", "p2"]})
        assert r.status_code == 200
        r2 = client.get("/api/v1/session/user-1/summary")
        assert r2.status_code == 200
        body = r2.json()
        assert body.get("summary_text")
        assert body.get("utterances_count") == 1
        assert body.get("retrieval_ranks") == ["p1", "p2"]
    finally:
        app.dependency_overrides.pop(get_redis, None)
