from typing import Any, Dict

from src.app.services.orchestrator import Orchestrator


class _FakeRedis:
    def __init__(self):
        self._kv: Dict[str, str] = {}

    def get(self, key: str):
        return self._kv.get(key)

    def setex(self, key: str, ttl: int, value: str):
        self._kv[key] = value


class _DummyMemory:
    def __init__(self):
        self.redis = _FakeRedis()

    def get_context(self, uid: str) -> Dict[str, Any]:
        return {"kv": {}}

    def set_recent_retrieval(self, uid: str, live: Dict[str, Any]) -> None:
        pass


class _DummyFirewall:
    def check_pricing(self, cart_total_cents: int, proposed_discount_percent: int):
        class _Result:
            allowed = True
            approval_required = False
            reason = "ok"
            escalation_role = None
            policy_version = "v1"

        return _Result()

    def idempotency_ok(self, exists: bool):
        return (not exists, "ok")


def test_incident_dedupe_supports_trace_and_idempotency_keys():
    orch = Orchestrator(memory=_DummyMemory(), firewall=_DummyFirewall(), flags={})
    assert orch._incident_already_ticketed("trace-1", "idem-1", "tenant-a") is False
    orch._mark_incident_ticketed("trace-1", "idem-1", "tenant-a")
    assert orch._incident_already_ticketed("trace-1", None, "tenant-a") is True
    assert orch._incident_already_ticketed(None, "idem-1", "tenant-a") is True


def test_incident_dedupe_scoped_by_tenant():
    orch = Orchestrator(memory=_DummyMemory(), firewall=_DummyFirewall(), flags={})
    orch._mark_incident_ticketed("trace-x", "idem-x", "tenant-a")
    assert orch._incident_already_ticketed("trace-x", "idem-x", "tenant-a") is True
    assert orch._incident_already_ticketed("trace-x", "idem-x", "tenant-b") is False
