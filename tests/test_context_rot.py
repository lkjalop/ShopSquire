from src.app.services.memory import Memory


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, _ttl, value):
        self.store[key] = value


def test_summary_truncates_over_50_utterances():
    fake = FakeRedis()
    mem = Memory(fake)
    uid = "u-rot"
    utterances = []
    for i in range(60):
        utterances.append(f"u{i}")
        summary = {"utterances": utterances[-50:], "summary_text": "; ".join(utterances[-10:])}
        mem.set_summary(uid, summary)
    ctx = mem.get_context(uid)
    stored = ctx.get("summary", {}).get("utterances", [])
    assert len(stored) == 50


def test_recent_retrieval_expires():
    fake = FakeRedis()
    mem = Memory(fake)
    uid = "u-ttl"
    mem.set_recent_retrieval(uid, {"facts": ["a", "b"]}, ttl_seconds=1)
    ctx = mem.get_context(uid)
    assert ctx.get("recent_retrieval") is not None
